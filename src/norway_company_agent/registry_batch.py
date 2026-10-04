"""Registry reads that fit a run-wide request budget (SPEC UC-6).

The starter reads five Brønnøysund endpoints per company (about 5.6 requests per company). Here:
- live entity rows: one search request per 300 organisation numbers;
- registered workplaces (subunits): one bulk download per run, streamed and filtered to the batch;
- roles: one bulk download per run, streamed and filtered to the batch;
- group structure: only for entities the live row marks `erIKonsern` (about 7%), one request each.
The pure parsers below take iterables; the network functions at the bottom only stream bytes into them.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import zlib
from typing import Any, Iterable, Iterator

from .evidence import evidence, utc_now
from .official import BRREG_ENTITY, normalize_entity, normalize_roles

ENTITY_SEARCH = "https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsnummer={orgs}&size={size}"
SUBUNIT_BULK = "https://data.brreg.no/enhetsregisteret/api/underenheter/lastned/csv"
ROLES_BULK = "https://data.brreg.no/enhetsregisteret/api/roller/totalbestand"


def entity_batch_urls(orgs: list[str], *, chunk: int = 300) -> list[str]:
    return [ENTITY_SEARCH.format(orgs=",".join(orgs[i:i + chunk]), size=len(orgs[i:i + chunk])) for i in range(0, len(orgs), chunk)]


def live_records_from_batch(orgs: Iterable[str], body: Any, *, retrieved_at: str, batch_url: str) -> dict[str, dict[str, Any]]:
    rows = ((body or {}).get("_embedded") or {}).get("enheter") or [] if isinstance(body, dict) else []
    by_org = {str(row.get("organisasjonsnummer")): row for row in rows if isinstance(row, dict)}
    out: dict[str, dict[str, Any]] = {}
    for org in orgs:
        row = by_org.get(org)
        if row is None:
            out[org] = evidence("registry_live", "not_found", "official_registry_live", BRREG_ENTITY.format(org=org),
                                retrieved_at=retrieved_at, note=f"Not returned by the registry search {batch_url[:120]}… (deleted or not public)")
            continue
        value = normalize_entity(row)
        value["in_group"] = row.get("erIKonsern")
        value["activity"] = row.get("aktivitet") or row.get("vedtektsfestetFormaal") or None
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        out[org] = evidence("registry_live", "available", "official_registry_live", BRREG_ENTITY.format(org=org), value=value,
                            retrieved_at=retrieved_at, content_sha256=digest,
                            note="Entity row read through the registry search endpoint (300 organisation numbers per request)")
    return out


def _email_domain(value: Any) -> str | None:
    text = str(value or "").strip().casefold()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip(". ")
    return domain if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain) else None


def subunits_from_csv(handle: Iterable[str], wanted: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Filter the Brreg subunit bulk CSV to the batch; same shape as official.normalize_locations (+ email_domain)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in csv.DictReader(handle):
        parent = (row.get("overordnetEnhet") or "").strip()
        if parent not in wanted:
            continue
        employees = (row.get("antallAnsatte") or "").strip()
        address = {
            "adresse": [part.strip() for part in (row.get("beliggenhetsadresse.adresse") or "").split(",") if part.strip()],
            "poststed": row.get("beliggenhetsadresse.poststed") or None,
            "postnummer": row.get("beliggenhetsadresse.postnummer") or None,
            "kommune": row.get("beliggenhetsadresse.kommune") or None,
            "kommunenummer": row.get("beliggenhetsadresse.kommunenummer") or None,
            "land": row.get("beliggenhetsadresse.land") or None,
            "landkode": row.get("beliggenhetsadresse.landkode") or None,
        }
        out.setdefault(parent, []).append({
            "organisation_number": row.get("organisasjonsnummer"),
            "name": row.get("navn"),
            "address": address,
            "industry": {"kode": row.get("naeringskode1.kode"), "beskrivelse": row.get("naeringskode1.beskrivelse")} if row.get("naeringskode1.kode") else None,
            "employees": int(employees) if employees.isdigit() else None,
            "website": (row.get("hjemmeside") or "").strip() or None,
            "email_domain": _email_domain(row.get("epostadresse")),
            "closed": bool((row.get("nedleggelsesdato") or "").strip()),
        })
    return out


_TOP_ORG = re.compile(r'"organisasjonsnummer"\s*:\s*"(\d{9})"')


def iter_role_elements(gz_chunks: Iterable[bytes], wanted: set[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Stream the gzip'd Brreg roles array (elements close with a column-0 '}' line) and yield only batch orgs."""
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buffer = ""

    def emit(text: str) -> Iterator[tuple[str, dict[str, Any]]]:
        text = text.strip().lstrip("[").strip().lstrip(",").strip()
        if not text:
            return
        match = _TOP_ORG.search(text)
        if match and match.group(1) in wanted:
            yield match.group(1), json.loads(text)

    for chunk in gz_chunks:
        buffer += inflater.decompress(chunk).decode("utf-8", errors="replace")
        start = 0
        while True:
            end = buffer.find("\n},", start)
            if end < 0:
                break
            yield from emit(buffer[start:end + 2])
            start = end + 3
        buffer = buffer[start:]
    buffer += inflater.flush().decode("utf-8", errors="replace")
    tail = buffer.rstrip().rstrip("]").rstrip()
    yield from emit(tail)


# --- network (adapters) -------------------------------------------------------------------------

def _open(url: str, timeout: float):
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "signalpost-exact-id-agent/2.0 (+https://github.com/Ryugi62/signalpost-agent)", "Accept": "*/*"})
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_live_entities(orgs: list[str], *, chunk: int = 300, fetcher: Any = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    from .http import fetch_json

    fetch = fetcher or (lambda url: fetch_json(url, attempts=2))
    out: dict[str, dict[str, Any]] = {}
    metrics = {"requests": 0, "chunks": 0, "errors": 0}
    for i, url in enumerate(entity_batch_urls(orgs, chunk=chunk)):
        part = orgs[i * chunk:(i + 1) * chunk]
        result = fetch(url)
        metrics["requests"] += 1
        metrics["chunks"] += 1
        if result.status == 200:
            out.update(live_records_from_batch(part, result.body, retrieved_at=result.retrieved_at or utc_now(), batch_url=url))
        else:
            metrics["errors"] += 1
            for org in part:
                out[org] = evidence("registry_live", "source_error", "official_registry_live", BRREG_ENTITY.format(org=org),
                                    note=f"registry search failed: {result.error}", retrieved_at=result.retrieved_at)
    return out, metrics


def fetch_subunits_bulk(wanted: set[str], *, timeout: float = 120.0) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    import gzip
    import io

    retrieved_at = utc_now()
    metrics: dict[str, Any] = {"requests": 1, "url": SUBUNIT_BULK}
    try:
        with _open(SUBUNIT_BULK, timeout) as response:
            text = io.TextIOWrapper(gzip.GzipFile(fileobj=response), encoding="utf-8-sig", newline="")
            found = subunits_from_csv(text, wanted)
    except Exception as exc:  # one failed bulk read must not drop envelopes
        note = f"subunit bulk download failed: {type(exc).__name__}: {str(exc)[:120]}"
        metrics["error"] = note
        return {org: evidence("locations", "source_error", "official_subunits", SUBUNIT_BULK, note=note, retrieved_at=retrieved_at) for org in wanted}, metrics
    out = {}
    for org in wanted:
        locations = [loc for loc in found.get(org, []) if not loc.get("closed")]
        digest = hashlib.sha256(json.dumps(locations, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        out[org] = evidence("locations", "available", "official_subunits", SUBUNIT_BULK,
                            value={"locations": locations}, retrieved_at=retrieved_at, content_sha256=digest, source_row_key=f"overordnetEnhet={org}",
                            note="Registered workplaces from the Brønnøysund subunit bulk file (one download per run; rows whose overordnetEnhet is this org, "
                                 f"hash over those rows); closed subunits excluded. Live check: https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}")
        out[org]["verify_url"] = f"https://virksomhet.brreg.no/nb/oppslag/enheter/{org}"
    metrics["orgs_with_locations"] = sum(1 for org in wanted if found.get(org))
    return out, metrics


def fetch_roles_bulk(wanted: set[str], *, timeout: float = 120.0) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    retrieved_at = utc_now()
    metrics: dict[str, Any] = {"requests": 1, "url": ROLES_BULK}
    found: dict[str, dict[str, Any]] = {}
    try:
        with _open(ROLES_BULK, timeout) as response:
            chunks = iter(lambda: response.read(1 << 20), b"")
            for org, element in iter_role_elements(chunks, wanted):
                found[org] = element
                if len(found) == len(wanted):
                    break
    except Exception as exc:
        note = f"roles bulk download failed: {type(exc).__name__}: {str(exc)[:120]}"
        metrics["error"] = note
        return {org: evidence("roles", "source_error", "official_roles", ROLES_BULK, note=note, retrieved_at=retrieved_at) for org in wanted}, metrics
    out = {}
    for org in wanted:
        live = BRREG_ENTITY.format(org=org) + "/roller"
        if org in found:
            digest = hashlib.sha256(json.dumps(found[org], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            out[org] = evidence("roles", "available", "official_roles", ROLES_BULK, value=normalize_roles(found[org]), retrieved_at=retrieved_at,
                                content_sha256=digest, source_row_key=org,
                                note=f"Roles from the Brønnøysund roles bulk file (one download per run; hash over this org's element). Live check: {live}")
        else:
            out[org] = evidence("roles", "not_found", "official_roles", ROLES_BULK, retrieved_at=retrieved_at, source_row_key=org,
                                note="No roles element for this organisation number in the roles bulk file")
        out[org]["verify_url"] = f"https://virksomhet.brreg.no/nb/oppslag/enheter/{org}"
    metrics["orgs_with_roles"] = len(found)
    return out, metrics

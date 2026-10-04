"""Network adapters for the footprint modules (DNS, company sites, NAV vacancy feed, Wikidata)."""
from __future__ import annotations

import hashlib
import re
import json
import socket
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Iterable

from ..evidence import evidence, utc_now
from ..identity import _sole_org_number, assess_social_identity, assess_website_identity
from ..website import SAFE_OPENER, USER_AGENT as SITE_USER_AGENT, _fetch_secondary_page, _robots_allowed, fetch_website
from .domain import _reg_domain, activity_allowed, domain_candidates, parse_feed_items, email_domain_candidate, identity_proof, name_key, name_tokens, parse_wikidata_bindings

USER_AGENT = "signalpost-exact-id-agent/2.0 (+https://github.com/Ryugi62/signalpost-agent)"
NAV_FEED = "https://pam-stilling-feed.nav.no"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
_DNS_POOL = ThreadPoolExecutor(max_workers=16)


def _resolves(host: str, timeout: float = 4.0) -> bool:
    future = _DNS_POOL.submit(socket.getaddrinfo, host, 443)
    try:
        return bool(future.result(timeout=timeout))
    except Exception:
        return False


def registry_contact(profile: dict[str, Any]) -> dict[str, Any]:
    live = ((profile.get("evidence") or {}).get("registry_live") or {}).get("value") or {}
    raw = ((profile.get("evidence") or {}).get("registry") or {}).get("value") or {}
    address = live.get("business_address") or live.get("forretningsadresse") or {}
    street = " ".join(address.get("adresse") or []) or raw.get("forretningsadresse.adresse") or ""
    postcode = address.get("postnummer") or raw.get("forretningsadresse.postnummer") or ""
    phone = live.get("phone") or live.get("telefon") or live.get("mobil") or raw.get("telefon") or ""
    return {"street": street, "postcode": postcode, "phone": phone}


def _page_texts(value: dict[str, Any]) -> list[str]:
    texts = [value.get("title"), value.get("description"), value.get("identity_text_excerpt"), value.get("main_text_excerpt")]
    for page in value.get("pages") or []:
        texts += [page.get("title"), page.get("identity_text_excerpt"), page.get("main_text_excerpt")]
    return [str(t or "") for t in texts]


MIN_FULL_SNAPSHOT_ROWS = 1_000_000


def registry_collisions(bulk_path: str | Path) -> dict[str, dict[str, int]] | None:
    """One pass over the bulk snapshot: how many entities share each e-mail domain, phone and street+postcode."""
    import csv
    import gzip

    from .domain import _phone_digits, address_key

    out: dict[str, dict[str, int]] = {"email_domain": {}, "phone": {}, "address": {}}
    rows = 0
    from ..sampling import open_bulk_text

    with open_bulk_text(bulk_path) as handle:
        reader = csv.DictReader(handle)
        needed = {"epostadresse", "telefon", "forretningsadresse.adresse", "forretningsadresse.postnummer"}
        if not needed <= set(reader.fieldnames or []):
            return None  # fail closed: uniqueness cannot be checked
        for row in reader:
            rows += 1
            email = (row.get("epostadresse") or "").strip().casefold()
            if "@" in email:
                domain = email.rsplit("@", 1)[1]
                out["email_domain"][domain] = out["email_domain"].get(domain, 0) + 1
            for field in ("telefon", "mobil"):
                phone = _phone_digits(row.get(field))
                if phone:
                    out["phone"][phone] = out["phone"].get(phone, 0) + 1
            key = address_key(row.get("forretningsadresse.adresse"), row.get("forretningsadresse.postnummer"))
            if key:
                out["address"][key] = out["address"].get(key, 0) + 1
    if rows < MIN_FULL_SNAPSHOT_ROWS:
        return None  # fail closed: a partial snapshot would make shared phones/addresses look unique
    return out


def _host_of(url: Any) -> str:
    return re.sub(r"^https?://", "", str(url or "").strip().casefold()).split("/")[0].split(":")[0].removeprefix("www.")


def secondary_pages_for(profile: dict[str, Any]):
    """Homepage-first crawl budget for a discovery candidate (UC-1, AC-19).

    Returns a function of the fetched homepage value: 1 secondary page when the exact org number is already on
    the homepage (enough for contact e-mail/socials), 2 when the full legal name is there but no proof yet, and 0
    when neither the name nor the org number appears (plainly not this company's site: stop after one page)."""
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    tokens = [t for t in name_tokens(profile.get("name")) if t not in {"og"}]

    def decide(value: dict[str, Any]) -> int:
        text = "\n".join(_page_texts(value))  # page content only: the hostname was generated from the name
        digits = re.sub(r"\D", "", text)
        if len(org) == 9 and org in digits:
            return 1
        from .domain import _ascii
        compact = re.sub(r"[^a-z0-9]", "", _ascii(text))
        if tokens and all(t in compact for t in tokens):
            return 2
        return 0

    return decide


def discover_website(profile: dict[str, Any], *, timeout: float = 10.0, max_fetches: int = 3, max_generated_fetches: int = 1,
                     collisions: dict[str, dict[str, int]] | None = None,
                     prior_record: dict[str, Any] | None = None, extra_hosts: Iterable[str] = (), can_spend: Any = None,
                     homepage_first: bool = True) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    """UC-1. Returns (published website evidence or None, discovery record, metrics).

    prior_record: the registry-declared website record the run already fetched (status available, not publishable by
    the starter's name gate). It is checked first with the same proof gate and costs no request (AC-17).
    extra_hosts: further registry- or Wikidata-declared domains (subunit e-mail domains, Wikidata P856); like other
    declared domains they need the org number unless the domain spells the full legal name (AC-18).
    can_spend(): optional budget check before each new site fetch.
    max_generated_fetches: name-generated candidates fetched at most this many times (v1 run on 1,000 companies:
    36 of 37 discoveries were the first site fetched; later candidates cost ~75% of discovery requests)."""
    name = profile.get("name")
    full_tokens = name_tokens(name)
    locations = (((profile.get("evidence") or {}).get("locations") or {}).get("value") or {}).get("locations") or []
    brands = list(dict.fromkeys(item.get("name") for item in locations if item.get("name")))[:2]
    candidates = domain_candidates(name, limit=6, brand_names=brands)
    raw = ((profile.get("evidence") or {}).get("registry") or {}).get("value") or {}
    email_host = email_domain_candidate(raw.get("epostadresse"), (collisions or {}).get("email_domain")) if collisions is not None else None
    if email_host:
        candidates = [email_host] + [c for c in candidates if c != email_host]
    registry_hosts: list[str] = []
    for item in locations[:5]:
        host = _host_of(item.get("website"))
        if host and "." in host and host not in candidates and host not in registry_hosts:
            registry_hosts.append(host)
    declared_extra: list[str] = []
    for host in extra_hosts:
        host = _host_of(host)
        if host and "." in host and host not in candidates and host not in registry_hosts and host not in declared_extra:
            declared_extra.append(host)
    prior_host = None
    if prior_record and prior_record.get("status") == "available":
        prior_host = _host_of((prior_record.get("value") or {}).get("requested_url") or prior_record.get("source_url"))
    candidates = registry_hosts[:2] + declared_extra[:2] + candidates
    if prior_host:
        candidates = [prior_host] + [c for c in candidates if c != prior_host]
    declared = set(registry_hosts) | set(declared_extra) | ({email_host} if email_host else set()) | ({prior_host} if prior_host else set())
    metrics = {"requests": 0, "bytes": 0, "latencies_ms": [], "dns_lookups": 0}
    attempts: list[dict[str, Any]] = []
    proof_profile = {"organisation_number": profile.get("organisation_number"), "name": name, "registry": registry_contact(profile)}
    fetches = 0
    generated_fetches = 0
    gate = secondary_pages_for(profile) if homepage_first else None
    for host in candidates:
        if host == prior_host:
            record = prior_record
            fetch_note = "registry-declared website already fetched (no new request)"
        else:
            metrics["dns_lookups"] += 1
            if not _resolves(host):
                attempts.append({"candidate": host, "result": "no_dns"})
                continue
            if fetches >= max_fetches or (host not in declared and generated_fetches >= max_generated_fetches):
                attempts.append({"candidate": host, "result": "fetch_budget_exhausted"})
                break
            if can_spend is not None and not can_spend():
                attempts.append({"candidate": host, "result": "run_request_budget_exhausted"})
                break
            fetches += 1
            generated_fetches += host not in declared
            record, fetch_metrics = fetch_website(f"https://{host}/", timeout=timeout, max_secondary=2, source_class="discovered_company_website",
                                                  **({"secondary_gate": gate} if gate is not None else {}))
            metrics["requests"] += fetch_metrics["requests"]
            metrics["bytes"] += fetch_metrics["bytes"]
            metrics["latencies_ms"] += fetch_metrics["latencies_ms"]
            fetch_note = None
        if record.get("status") != "available":
            attempts.append({"candidate": host, "result": record.get("status"), "note": record.get("note")})
            continue
        value = dict(record.get("value") or {})
        value["pages"] = list(value.get("pages") or [])
        from_email = host in declared  # registry/Wikidata-declared domain (e-mail, subunit website, entity website)
        host_base = host.split(".")[-2].replace("-", "") if from_email else host.rsplit(".", 1)[0].replace("-", "")
        final_label = str(value.get("registered_domain") or "").split(".")[0].replace("-", "")
        redirected = final_label != host_base
        if redirected:
            # Another domain: could be the company's brand domain, or a directory / parent-group page.
            # Accept only a root-level page whose site shows this org number and no other org number.
            path_depth = len([seg for seg in urllib.parse.urlparse(value.get("final_url") or "").path.split("/") if seg])
            texts = _page_texts(value)
            strict = identity_proof({"organisation_number": profile.get("organisation_number"), "name": name}, texts, allow_contact=False)
            if path_depth > 1 or strict["proof"] != "org" or not _sole_org_number(str(profile.get("organisation_number")), "\n".join(texts)):
                attempts.append({"candidate": host, "final_url": value.get("final_url"), "result": "redirected_off_candidate"})
                continue
        # Contact proofs only on a domain spelled like the full legal name; registry-declared domains with another
        # label (group/firm sites such as gaiaarkitekter.no for GAIA LISTA AS) need the exact org number.
        full_name_host = host_base == "".join(t for t in full_tokens if t != "og") and host.endswith(".no")  # .com: org number only
        proof = identity_proof(proof_profile, _page_texts(value), allow_contact=full_name_host, collisions=collisions)
        # Registry e-mail domains get no name-only shortcut: an address-named holding company can list its
        # owner's e-mail (CARLBERGVEIEN 7 AS -> personalpartner.no, fresh audit 2026-10-04), so org or unique-contact proof is required.
        if (proof["proof"] == "none" and "not all present" not in proof["reason"] and (can_spend is None or can_spend())
                and len(value["pages"]) <= 1):
            # Name matches but no corroboration yet and no secondary page was read (the homepage had no contact/about
            # link): try the two conventional contact paths (bounded, same domain).
            seen = {pg.get("url", "").rstrip("/") for pg in value.get("pages") or []}
            base = (value.get("final_url") or f"https://{host}/").rstrip("/")
            base = urllib.parse.urlunparse(urllib.parse.urlparse(base)._replace(path="", params="", query="", fragment="")).rstrip("/")
            for path in ("/kontakt", "/kontakt-oss"):
                url = base + path
                if url in seen:
                    continue
                page, _social, req, nbytes, elapsed, err = _fetch_secondary_page(url, homepage_domain=value.get("registered_domain") or host, timeout=timeout, max_bytes=1_000_000)
                metrics["requests"] += req
                metrics["bytes"] += nbytes
                if page:
                    value["pages"].append(page)
                    proof = identity_proof(proof_profile, _page_texts(value), allow_contact=full_name_host, collisions=collisions)
                    break
                if can_spend is not None and not can_spend():
                    break
        attempt = {"candidate": host, "final_url": value.get("final_url"), "result": proof["proof"], "reason": proof["reason"]}
        if fetch_note:
            attempt["note"] = fetch_note
        attempts.append(attempt)
        qualifiers = {"norway", "norge", "norden", "nordic", "nordics", "scandinavia", "skandinavia", "europe", "international", "group", "holding"}
        label_compact = str(value.get("registered_domain") or host).split(".")[0].replace("-", "")
        missing_qualifier = [t for t in full_tokens if t in qualifiers and t not in label_compact]
        if proof["proof"] in {"contact", "registry_email"} and missing_qualifier:
            # e.g. "ENRY NORWAY AS" on enry.com: likely the international brand/parent site, not this exact entity.
            attempts.append({"candidate": host, "final_url": value.get("final_url"), "result": "brand_or_parent_site",
                             "reason": f"legal-name qualifier {missing_qualifier} absent from the domain; only an org-number proof is accepted"})
            continue
        if proof["proof"] in {"org", "contact", "registry_email"}:
            source = ("the registry website field of this entity" if host == prior_host else
                      f"domain {host} declared in the registry (e-mail or subunit website) or on Wikidata" if from_email else
                      f"domain candidate {host} generated from the legal name")
            value["identity_assessment"] = {
                "status": "exact", "score": 1.0 if proof["proof"] == "org" else 0.95, "publishable": True,
                "legal_name_tokens": full_tokens, "matched_tokens": full_tokens,
                "proof_snippet": proof.get("snippet"),
                "reasons": [proof["reason"], source + "; search results not used"],
                "method": f"deterministic_domain_discovery_{proof['proof']}_proof_v1",
            }
            original = list(value.get("discovered_social_links") or value.get("social_links") or [])
            value["discovered_social_links"] = original
            assessments = [assess_social_identity(profile, link) for link in original]
            value["social_link_assessments"] = assessments
            value["social_links"] = [{"platform": a["platform"], "url": a["url"]} for a in assessments if a["publishable"]]
            record = {**record, "value": value}
            if host == prior_host:
                record["note"] = "Registry-declared company site; exact identity proven on the site itself (org number or registry-unique contact)"
            else:
                record["source_class"] = record["source_type"] = "discovered_company_website"
                record["note"] = "Discovered company-owned site; exact identity proven on the site itself (not a search result)"
            discovery = evidence("website_discovery", "available", "deterministic_domain_discovery", record["source_url"],
                                 value={"candidates": candidates, "attempts": attempts, "published": host})
            return record, discovery, metrics
    status = "ambiguous" if any(a.get("result") == "none" for a in attempts) else "not_found"
    discovery = evidence("website_discovery", "not_found" if status == "not_found" else "available",
                         "deterministic_domain_discovery", f"https://{candidates[0]}/" if candidates else "about:blank",
                         value={"candidates": candidates, "attempts": attempts, "published": None, "state": status},
                         note="Candidates without on-site identity proof are withheld (never published)")
    if status == "ambiguous":
        discovery["status"] = "ambiguous"
    return None, discovery, metrics


# --- Dated activity from the verified site's own feed (AC-22, AC-23) ---------------------------------

def _get_feed(url: str, max_bytes: int = 1_000_000, timeout: float = 10.0) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": SITE_USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8"})
    with SAFE_OPENER.open(request, timeout=timeout) as response:
        return response.read(max_bytes), response.geturl()


def attach_feed_activity(site: dict[str, Any], *, name: Any = None, now: str | None = None, timeout: float = 10.0) -> int:
    """For a website record that passed the identity gate and declares its own posts feed, read that feed once and
    keep its dated posts under value.feed_activity. Returns the number of feed fetches attempted (0 or 1).
    robots.txt is honoured (normally already cached from the homepage fetch). Errors are recorded, never raised."""
    value = site.get("value") if isinstance(site.get("value"), dict) else None
    if site.get("status") != "available" or not value or not (value.get("identity_assessment") or {}).get("publishable"):
        return 0
    url = value.get("feed_link")
    if not url or value.get("feed_activity"):
        return 0
    if not activity_allowed(value, name):
        return 0  # a registry-declared group/brand site: its news is the group's, so the request is not spent
    record: dict[str, Any] = {"feed_url": url, "items": [], "retrieved_at": utc_now()}
    try:
        if not _robots_allowed(url, timeout):
            record["error"] = "robots.txt disallows the feed"
        else:
            body, final_url = _get_feed(url, timeout=timeout)
            record["content_sha256"] = hashlib.sha256(body).hexdigest()
            if _reg_domain(final_url) != _reg_domain(url):
                record["error"] = "feed redirected off the site's domain"
            else:
                record["items"] = parse_feed_items(body.decode("utf-8", errors="replace"), feed_url=final_url,
                                                   site_domain=value.get("registered_domain") or _reg_domain(value.get("final_url")),
                                                   now=now or utc_now())
    except Exception as exc:  # budget refusals and network errors leave an empty, explained record
        record["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    value["feed_activity"] = record
    return 1


# --- NAV public vacancy feed (UC-2) ---------------------------------------------------------

def _get(url: str, headers: dict[str, str], timeout: float = 30.0) -> tuple[bytes, int]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    return body, int((time.monotonic() - started) * 1000)


def nav_public_token() -> str:
    body, _ = _get(f"{NAV_FEED}/api/publicToken", {})
    return body.decode().strip().splitlines()[-1].strip()


def nav_active_entries(days: int, *, cache_dir: Path | None = None, max_pages: int = 400) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Walk the feed from now-days; keep the latest state per ad. Returns ACTIVE entries keyed by uuid."""
    metrics = {"requests": 0, "bytes": 0, "pages": 0}
    token = nav_public_token()
    metrics["requests"] += 1
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    since = datetime.now(timezone.utc) - timedelta(days=days)
    url = f"{NAV_FEED}/api/v1/feed"
    first_headers = {**headers, "If-Modified-Since": format_datetime(since, usegmt=True)}
    latest: dict[str, dict[str, Any]] = {}
    page_hashes = []
    while url and metrics["pages"] < max_pages:
        try:
            body, _ = _get(url, first_headers if metrics["pages"] == 0 else headers)
        except Exception as exc:
            metrics["requests"] += 1
            if not metrics["pages"]:
                raise
            metrics["truncated"] = f"{type(exc).__name__}: {str(exc)[:120]}"  # keep the pages already read
            break
        metrics["requests"] += 1
        metrics["bytes"] += len(body)
        metrics["pages"] += 1
        page_hashes.append(hashlib.sha256(body).hexdigest())
        page = json.loads(body)
        for item in page.get("items") or []:
            entry = item.get("_feed_entry") or {}
            latest[entry.get("uuid") or item.get("id")] = {**entry, "feed_url": NAV_FEED + item.get("url", "")}
        next_url = page.get("next_url")
        if not next_url or not page.get("items"):
            break
        url = NAV_FEED + next_url
    if url and metrics["pages"] >= max_pages:
        metrics["truncated"] = f"page cap {max_pages} reached"
    active = {k: v for k, v in latest.items() if v.get("status") == "ACTIVE"}
    metrics["feed_sha256"] = hashlib.sha256("".join(page_hashes).encode()).hexdigest()
    metrics["active_entries"] = len(active)
    return active, metrics


def nav_detail(uuid: str, token: str) -> tuple[dict[str, Any] | None, str | None]:
    body, _ = _get(f"{NAV_FEED}/api/v1/feedentry/{uuid}", {"Authorization": f"Bearer {token}", "Accept": "application/json"})
    data = json.loads(body)
    content = data.get("ad_content")
    if not content:
        return None, hashlib.sha256(body).hexdigest()
    return content, hashlib.sha256(body).hexdigest()


def nav_jobs_for_batch(orgs: dict[str, dict[str, Any]], *, days: int = 60, max_details: int = 300, prefetched: Any = None) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """orgs: org -> {name, subunits:[org], subunit_names:[str]}. Returns org -> jobs evidence."""
    from .domain import match_jobs_to_orgs

    retrieved_at = utc_now()
    try:
        if prefetched is not None:
            active, metrics = prefetched.result() if hasattr(prefetched, "result") else prefetched
        else:
            active, metrics = nav_active_entries(days)
        metrics = dict(metrics)
    except Exception as exc:  # feed failure must not drop envelopes
        err = f"{type(exc).__name__}: {str(exc)[:160]}"
        return {org: evidence("jobs", "source_error", "nav_public_vacancy_feed", f"{NAV_FEED}/api/v1/feed", note=err) for org in orgs}, {"requests": 1, "error": err}
    keys: dict[str, set[str]] = {}
    for org, info in orgs.items():
        for name in [info.get("name"), *(info.get("subunit_names") or [])]:
            key = name_key(name)
            if key and len(key) >= 3:
                keys.setdefault(key, set()).add(org)
    candidates = [uuid for uuid, entry in active.items() if name_key(entry.get("businessName")) in keys]
    token = nav_public_token()
    metrics["requests"] += 1
    details = []
    for uuid in candidates[:max_details]:
        try:
            content, digest = nav_detail(uuid, token)
            metrics["requests"] += 1
        except Exception:
            metrics["requests"] += 1
            continue
        if content:
            expires = str(content.get("expires") or "")
            if expires and expires[:10] < utc_now()[:10]:
                continue  # expired ad: not a current hiring signal
            content["_sha256"] = digest
            details.append(content)
    matched = match_jobs_to_orgs(details, orgs)
    metrics.update({"name_candidates": len(candidates), "details_fetched": len(details), "orgs_with_jobs": len(matched)})
    out: dict[str, dict[str, Any]] = {}
    for org in orgs:
        items = []
        for content in matched.get(org, []):
            loc = (content.get("workLocations") or [{}])[0]
            items.append({
                "title": content.get("title"),
                "jobtitle": content.get("jobtitle"),
                "published": content.get("published"),
                "expires": content.get("expires"),
                "application_due": content.get("applicationDue"),
                "workplace": ", ".join(x for x in [loc.get("address"), loc.get("postalCode"), loc.get("city")] if x),
                "employer_orgnr": (content.get("employer") or {}).get("orgnr"),
                "employer_name": (content.get("employer") or {}).get("name"),
                "occupation": [c.get("level2") for c in content.get("occupationCategories") or []],
                "url": content.get("link") or f"https://arbeidsplassen.nav.no/stillinger/stilling/{content.get('uuid')}",
                "api_url": f"{NAV_FEED}/api/v1/feedentry/{content.get('uuid')}",
                "content_sha256": content.get("_sha256"),
            })
        if items:
            out[org] = evidence("jobs", "available", "nav_public_vacancy_feed", items[0]["api_url"],
                                value={"items": items, "count": len(items), "window_days": days,
                                       "identity": "employer.orgnr equals the organisation or one of its registered subunits"},
                                retrieved_at=retrieved_at, content_sha256=items[0]["content_sha256"])
        else:
            out[org] = evidence("jobs", "not_found", "nav_public_vacancy_feed", f"{NAV_FEED}/api/v1/feed",
                                value={"items": [], "count": 0, "window_days": days, "feed_sha256": metrics.get("feed_sha256")},
                                retrieved_at=retrieved_at,
                                note=f"No ACTIVE NAV vacancy with this employer org number (or its subunits) in the last {days} days of the feed")
    return out, metrics


# --- Wikidata bridge (UC-3) -----------------------------------------------------------------

def wikidata_for_batch(orgs: Iterable[str], *, chunk: int = 400) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    orgs = list(orgs)
    retrieved_at = utc_now()
    metrics = {"requests": 0, "bytes": 0}
    bindings: list[dict[str, Any]] = []
    hashes = []
    error = None
    for start in range(0, len(orgs), chunk):
        values = " ".join(f'"{o}"' for o in orgs[start:start + chunk])
        query = (
            "SELECT ?item ?org ?website ?facebook ?instagram ?linkedin ?youtube ?x WHERE { "
            f"VALUES ?org {{ {values} }} ?item wdt:P2333 ?org . "
            "OPTIONAL { ?item wdt:P856 ?website } OPTIONAL { ?item wdt:P2013 ?facebook } "
            "OPTIONAL { ?item wdt:P2003 ?instagram } OPTIONAL { ?item wdt:P4264 ?linkedin } "
            "OPTIONAL { ?item wdt:P2397 ?youtube } OPTIONAL { ?item wdt:P2002 ?x } }"
        )
        data = urllib.parse.urlencode({"query": query}).encode()
        request = urllib.request.Request(WIKIDATA_SPARQL, data=data, headers={
            "User-Agent": USER_AGENT, "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
            metrics["requests"] += 1
            metrics["bytes"] += len(body)
            hashes.append(hashlib.sha256(body).hexdigest())
            bindings += json.loads(body)["results"]["bindings"]
        except Exception as exc:
            metrics["requests"] += 1
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
    parsed = parse_wikidata_bindings(bindings)
    digest = hashlib.sha256("".join(hashes).encode()).hexdigest() if hashes else None
    out = {}
    for org in orgs:
        claims = parsed.get(org) or []
        if claims:
            out[org] = evidence("wikidata", "available", "wikidata_cc0_org_number_match", claims[0]["source_url"],
                                value={"claims": claims, "licence": "CC0 1.0"}, retrieved_at=retrieved_at, content_sha256=digest)
        elif error:
            out[org] = evidence("wikidata", "source_error", "wikidata_cc0_org_number_match", WIKIDATA_SPARQL, note=error, retrieved_at=retrieved_at)
        else:
            out[org] = evidence("wikidata", "not_found", "wikidata_cc0_org_number_match", WIKIDATA_SPARQL,
                                note="No Wikidata item carries this Norwegian organisation number (P2333)", retrieved_at=retrieved_at, content_sha256=digest)
    metrics["orgs_with_claims"] = sum(1 for v in out.values() if v["status"] == "available")
    return out, metrics

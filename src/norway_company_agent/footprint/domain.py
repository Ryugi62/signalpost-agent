"""Pure footprint logic: no network, no framework imports (SPEC §7)."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

LEGAL_FORMS = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "nuf", "ks", "bbl", "brl",
    "ba", "ab", "gmbh", "ltd", "limited", "inc", "plc", "aps", "oy", "bv",
}
STOP = {"og", "the", "and", "i", "pa", "av", "for", "til"}
_TRANS = str.maketrans({"ø": "o", "Ø": "o", "å": "a", "Å": "a", "æ": "ae", "Æ": "ae", "&": " og "})
SEP = r"[\s.\- ]?"


def _ascii(value: Any) -> str:
    text = str(value or "").translate(_TRANS)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def name_tokens(name: Any) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _ascii(name)) if t not in LEGAL_FORMS]


def name_key(name: Any) -> str:
    return " ".join(name_tokens(name))


def _label_ok(base: str) -> bool:
    return 3 <= len(base) <= 63 and not base.isdigit() and not base.startswith("-") and not base.endswith("-")


def _alt_ascii_tokens(name: Any) -> list[str]:
    """Second spelling for Norwegian letters (å→aa, ø→oe, æ→ae), used only when the name contains them."""
    raw = str(name or "")
    if not any(ch in raw for ch in "åÅøØ"):
        return []
    text = raw.translate(str.maketrans({"ø": "oe", "Ø": "oe", "å": "aa", "Å": "aa", "æ": "ae", "Æ": "ae", "&": " og "}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [t for t in re.findall(r"[a-z0-9]+", text) if t not in LEGAL_FORMS and t != "og"]


def domain_candidates(name: Any, *, limit: int = 4, brand_names: Iterable[Any] = ()) -> list[str]:
    """Deterministic .no hostnames from the legal name (and registered subunit names). Candidates, never evidence."""
    tokens = [t for t in name_tokens(name) if t not in {"og"}]
    if not tokens:
        return []
    bases = ["".join(tokens), "-".join(tokens)]
    for brand in brand_names:
        brand_tokens = [t for t in name_tokens(brand) if t not in {"og", "avd", "avdeling"}]
        if brand_tokens and brand_tokens != tokens:
            bases.append("".join(brand_tokens))
    alt = _alt_ascii_tokens(name)
    if alt and alt != tokens:
        bases.append("".join(alt))
    if len(tokens) > 2:
        bases += ["".join(tokens[:2]), "-".join(tokens[:2])]
    out: list[str] = []
    for base in bases:
        if _label_ok(base):
            host = f"{base}.no"
            if host not in out:
                out.append(host)
    return out[:limit]


FREE_MAIL = {
    "gmail.com", "googlemail.com", "online.no", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.no", "live.com",
    "yahoo.no", "yahoo.com", "c2i.net", "lyse.net", "me.com", "icloud.com", "mac.com", "broadpark.no", "frisurf.no", "start.no",
    "msn.com", "getmail.no", "altibox.no", "tele2.no", "chello.no", "bluezone.no", "sensewave.com", "ebnett.no", "haugnett.no",
    "loqal.no", "monet.no", "vikenfiber.no", "netcom.no", "telia.no", "ice.no", "protonmail.com", "proton.me", "aol.com", "gmx.com",
    "mail.com", "yandex.com", "pm.me", "hotmail.se", "live.se",
}


def email_domain_candidate(email: Any, shared_counts: dict[str, int] | None = None, *, max_shared: int = 3) -> str | None:
    """Registry-declared e-mail domain as a site candidate; free-mail and shared (manager/accountant/group) domains excluded."""
    text = str(email or "").strip().casefold()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip(". ")
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain) or domain in FREE_MAIL:
        return None
    if shared_counts is not None and shared_counts.get(domain, 0) > max_shared:
        return None
    return domain


def _digits_pattern(digits: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\d)" + SEP.join(re.escape(d) for d in digits) + r"(?!\d)")


def _phone_digits(phone: Any) -> str | None:
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("0047"):
        digits = digits[4:]
    elif digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    return digits if len(digits) == 8 else None


ORG_LIKE = re.compile(r"(?<!\d)[89](?:[\s.\u00a0]?\d){8}(?!\d)")


def _other_org_numbers(org: str, text: str) -> set[str]:
    found = {re.sub(r"\D", "", m) for m in ORG_LIKE.findall(text)}
    found.discard(org)
    return found


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _snippet(text: str, match: re.Match[str]) -> str:
    """Short evidence span around the proof; e-mail addresses are masked (no personal contact data in output)."""
    span = re.sub(r"\s+", " ", text[max(0, match.start() - 30): match.end() + 10]).strip()
    return EMAIL_RE.sub("[e-mail]", span)


def address_key(street: Any, postcode: Any) -> str | None:
    tokens = [t for t in re.findall(r"[a-z0-9]+", _ascii(street)) if t not in {"postboks", "pb"}]
    code = re.sub(r"\D", "", str(postcode or ""))
    return f"{' '.join(tokens)}|{code}" if tokens and len(code) == 4 else None


def identity_proof(
    profile: dict[str, Any],
    page_texts: Iterable[str],
    *,
    allow_contact: bool = True,
    collisions: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Exact-entity proof for a candidate site. Returns proof in {org, contact, none} and the matched snippet.

    - org: the exact org number appears on a page that shows no other org number (rules out directories/group lists).
    - contact (only when allow_contact): all legal-name tokens + a registry phone or street+postcode that is held by
      exactly one registry entity (collisions), and the page lists no other org number.
    allow_contact=False is used for truncated/brand candidates, where only the org number may prove identity."""
    texts = [str(t or "") for t in page_texts]
    joined = "\n".join(texts)
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    if len(org) == 9:
        pattern = _digits_pattern(org)
        for text in texts:
            match = pattern.search(text)
            if match and not _other_org_numbers(org, text):
                return {"proof": "org", "reason": "exact organisation number on a fetched page of the candidate site (no other org number on that page)", "snippet": _snippet(text, match)}
        if pattern.search(joined):
            return {"proof": "none", "reason": "org number appears only on a page listing other org numbers (directory or group page)"}
    if not allow_contact:
        return {"proof": "none", "reason": "truncated-name candidate requires the exact organisation number"}
    tokens = [t for t in name_tokens(profile.get("name")) if t not in STOP]
    compact_page = re.sub(r"[^a-z0-9]", "", _ascii(joined))
    if not tokens or not all(t in compact_page for t in tokens):
        return {"proof": "none", "reason": "legal-name tokens not all present"}
    if _other_org_numbers(org, joined):
        return {"proof": "none", "reason": "site pages list other org numbers; name+contact proof not accepted"}
    reg = profile.get("registry") or {}
    phones = (collisions or {}).get("phone") or {}
    addresses = (collisions or {}).get("address") or {}
    phone = _phone_digits(reg.get("phone"))
    if phone and (collisions is None or phones.get(phone, 0) == 1):
        match = _digits_pattern(phone).search(joined)
        if match:
            return {"proof": "contact", "reason": "legal name + registry phone (unique to this entity in the registry) on a fetched page", "snippet": match.group(0)}
    postcode = re.sub(r"\D", "", str(reg.get("postcode") or ""))
    street_tokens = [t for t in re.findall(r"[a-z]{3,}", _ascii(reg.get("street"))) if t not in {"postboks", "pb"}]
    key = address_key(reg.get("street"), reg.get("postcode"))
    if (
        len(postcode) == 4
        and street_tokens
        and (collisions is None or (key and addresses.get(key, 0) == 1))
        and all(t in compact_page for t in street_tokens)
    ):
        match = re.search(r"(?<!\d)" + postcode + r"(?!\d)", joined)
        if match:
            return {"proof": "contact", "reason": "legal name + registry street and postcode (unique to this entity in the registry) on a fetched page", "snippet": f"{' '.join(street_tokens)} … {match.group(0)}"}
    return {"proof": "none", "reason": "name matches but no unique org number, phone or address corroboration"}


def match_jobs_to_orgs(details: Iterable[dict[str, Any]], orgs: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    owner: dict[str, str] = {}
    for org, info in orgs.items():
        owner[org] = org
        for sub in info.get("subunits") or []:
            owner.setdefault(str(sub), org)
    out: dict[str, list[dict[str, Any]]] = {}
    for detail in details:
        employer_org = str((detail.get("employer") or {}).get("orgnr") or "")
        parent = owner.get(employer_org)
        if parent:
            out.setdefault(parent, []).append(detail)
    return out


WIKIDATA_FIELDS = {
    "website": ("official_website", "{}"),
    "facebook": ("facebook", "https://www.facebook.com/{}"),
    "instagram": ("instagram", "https://www.instagram.com/{}/"),
    "linkedin": ("linkedin", "https://www.linkedin.com/company/{}/"),
    "youtube": ("youtube", "https://www.youtube.com/channel/{}"),
    "x": ("x", "https://x.com/{}"),
}


def parse_wikidata_bindings(bindings: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for row in bindings:
        org = re.sub(r"\D", "", (row.get("org") or {}).get("value", ""))
        item = (row.get("item") or {}).get("value", "")
        qid = item.rsplit("/", 1)[-1]
        if len(org) != 9 or not qid.startswith("Q"):
            continue
        for key, (field, template) in WIKIDATA_FIELDS.items():
            raw = (row.get(key) or {}).get("value")
            if not raw:
                continue
            value = template.format(raw.strip())
            out.setdefault(org, {})[(field, value)] = {
                "field": field,
                "value": value,
                "availability": "available",
                "source_url": f"https://www.wikidata.org/wiki/{qid}",
                "source_class": "wikidata_cc0_org_number_match",
                "method": "wikidata_P2333_exact_org_number",
            }
    # An org number carried by more than one Wikidata item is ambiguous: publish nothing for it.
    items_per_org: dict[str, set[str]] = {}
    for org, claims in out.items():
        items_per_org[org] = {c["source_url"] for c in claims.values()}
    return {org: list(v.values()) for org, v in out.items() if len(items_per_org[org]) == 1}


def _state(status: str | None) -> str:
    return {
        "available": "available",
        "not_found": "not_available",
        "not_applicable": "not_applicable",
        "blocked": "blocked",
        "ambiguous": "ambiguous",
        "source_error": "failed",
    }.get(str(status or ""), "failed")


def flatten_external_claims(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Claim-level view (OUTPUT_CONTRACT shape) for the external field families."""
    ev = profile.get("evidence") or {}
    claims: list[dict[str, Any]] = []
    site = ev.get("website") or {}
    value = site.get("value") or {}
    assessment = value.get("identity_assessment") or {}
    if site.get("status") == "available" and assessment.get("publishable"):
        claims.append({
            "field": "official_website", "value": value.get("final_url") or site.get("source_url"),
            "availability": "available", "source_url": site.get("source_url"),
            "source_class": site.get("source_class"), "retrieved_at": site.get("retrieved_at"),
            "content_sha256": site.get("content_sha256"), "method": assessment.get("method"),
            "identity_reason": "; ".join(assessment.get("reasons") or []),
            "proof_snippet": assessment.get("proof_snippet"),
            "date_basis": "retrieved_at (live company page; no publication date)",
        })
        for link in value.get("social_links") or []:
            claims.append({
                "field": link.get("platform"), "value": link.get("url"), "availability": "available",
                "source_url": value.get("final_url") or site.get("source_url"),
                "source_class": "verified_company_site_outbound_link", "retrieved_at": site.get("retrieved_at"),
                "content_sha256": site.get("content_sha256"), "method": "company_site_social_link",
                "date_basis": "retrieved_at of the verified company page that links to the profile",
            })
    else:
        discovery = ev.get("website_discovery") or {}
        state = "ambiguous" if site.get("status") == "available" or discovery.get("status") == "ambiguous" else _state(site.get("status") or "not_found")
        attempts = ((discovery.get("value") or {}).get("attempts") or []) if isinstance(discovery.get("value"), dict) else []
        claims.append({"field": "official_website", "value": None, "availability": state,
                       "source_url": site.get("source_url") or discovery.get("source_url"),
                       "retrieved_at": site.get("retrieved_at") or discovery.get("retrieved_at"),
                       "checked": ["registry website field"] + [f"{a.get('candidate')}: {a.get('result')}" for a in attempts],
                       "note": "Not found by the methods listed in 'checked' as of retrieved_at; uncertain matches are withheld."})
    jobs = ev.get("jobs") or {}
    items = (jobs.get("value") or {}).get("items") or [] if isinstance(jobs.get("value"), dict) else []
    if jobs.get("status") == "available" and items:
        for job in items:
            claims.append({
                "field": "job_postings", "value": {k: job.get(k) for k in ("title", "published", "expires", "workplace", "employer_orgnr")},
                "availability": "available", "source_url": job.get("url"), "source_class": "nav_public_vacancy_feed",
                "retrieved_at": jobs.get("retrieved_at"), "effective_at": job.get("published"), "expires_at": job.get("expires"),
                "date_basis": "NAV ad published/expires dates",
                "content_sha256": job.get("content_sha256"), "method": "nav_employer_orgnr_exact",
            })
    else:
        claims.append({"field": "job_postings", "value": None, "availability": _state(jobs.get("status") or "not_found"),
                       "source_url": jobs.get("source_url"), "retrieved_at": jobs.get("retrieved_at")})
    wikidata = ev.get("wikidata") or {}
    for claim in ((wikidata.get("value") or {}).get("claims") or []) if isinstance(wikidata.get("value"), dict) else []:
        claims.append({**claim, "retrieved_at": wikidata.get("retrieved_at"), "content_sha256": wikidata.get("content_sha256"),
                       "date_basis": "retrieved_at of the Wikidata SPARQL response (CC0)"})
    return claims

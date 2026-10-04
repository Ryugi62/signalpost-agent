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


def _digits_pattern(digits: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\d)" + SEP.join(re.escape(d) for d in digits) + r"(?!\d)")


def _phone_digits(phone: Any) -> str | None:
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("0047"):
        digits = digits[4:]
    elif digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    return digits if len(digits) == 8 else None


def identity_proof(profile: dict[str, Any], page_texts: Iterable[str], *, allow_contact: bool = True) -> dict[str, Any]:
    """Exact-entity proof for a candidate site. Returns proof in {org, contact, none}.

    allow_contact=False is used for truncated-name candidates, where only the org number may prove identity."""
    texts = [str(t or "") for t in page_texts]
    joined = "\n".join(texts)
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    if len(org) == 9 and _digits_pattern(org).search(joined):
        return {"proof": "org", "reason": "exact organisation number on a fetched page of the candidate site"}
    if not allow_contact:
        return {"proof": "none", "reason": "truncated-name candidate requires the exact organisation number"}
    tokens = [t for t in name_tokens(profile.get("name")) if t not in STOP]
    compact_page = re.sub(r"[^a-z0-9]", "", _ascii(joined))
    if not tokens or not all(t in compact_page for t in tokens):
        return {"proof": "none", "reason": "legal-name tokens not all present"}
    reg = profile.get("registry") or {}
    phone = _phone_digits(reg.get("phone"))
    if phone and _digits_pattern(phone).search(joined):
        return {"proof": "contact", "reason": "legal name + registry phone on a fetched page"}
    postcode = re.sub(r"\D", "", str(reg.get("postcode") or ""))
    street_tokens = [t for t in re.findall(r"[a-z]{3,}", _ascii(reg.get("street"))) if t not in {"postboks", "pb"}]
    if (
        len(postcode) == 4
        and re.search(r"(?<!\d)" + postcode + r"(?!\d)", joined)
        and street_tokens
        and all(t in compact_page for t in street_tokens)
    ):
        return {"proof": "contact", "reason": "legal name + registry street and postcode on a fetched page"}
    return {"proof": "none", "reason": "name matches but no org number, phone or address corroboration"}


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
    return {org: list(v.values()) for org, v in out.items()}


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
        })
        for link in value.get("social_links") or []:
            claims.append({
                "field": link.get("platform"), "value": link.get("url"), "availability": "available",
                "source_url": value.get("final_url") or site.get("source_url"),
                "source_class": "verified_company_site_outbound_link", "retrieved_at": site.get("retrieved_at"),
                "content_sha256": site.get("content_sha256"), "method": "company_site_social_link",
            })
    else:
        discovery = ev.get("website_discovery") or {}
        state = "ambiguous" if site.get("status") == "available" or discovery.get("status") == "ambiguous" else _state(site.get("status") or "not_found")
        claims.append({"field": "official_website", "value": None, "availability": state,
                       "source_url": site.get("source_url") or discovery.get("source_url"),
                       "retrieved_at": site.get("retrieved_at") or discovery.get("retrieved_at")})
    jobs = ev.get("jobs") or {}
    items = (jobs.get("value") or {}).get("items") or [] if isinstance(jobs.get("value"), dict) else []
    if jobs.get("status") == "available" and items:
        for job in items:
            claims.append({
                "field": "job_postings", "value": {k: job.get(k) for k in ("title", "published", "expires", "workplace", "employer_orgnr")},
                "availability": "available", "source_url": job.get("url"), "source_class": "nav_public_vacancy_feed",
                "retrieved_at": jobs.get("retrieved_at"), "effective_at": job.get("published"),
                "content_sha256": job.get("content_sha256"), "method": "nav_employer_orgnr_exact",
            })
    else:
        claims.append({"field": "job_postings", "value": None, "availability": _state(jobs.get("status") or "not_found"),
                       "source_url": jobs.get("source_url"), "retrieved_at": jobs.get("retrieved_at")})
    wikidata = ev.get("wikidata") or {}
    for claim in ((wikidata.get("value") or {}).get("claims") or []) if isinstance(wikidata.get("value"), dict) else []:
        claims.append({**claim, "retrieved_at": wikidata.get("retrieved_at"), "content_sha256": wikidata.get("content_sha256")})
    return claims

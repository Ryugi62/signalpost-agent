"""Deterministic, cited company brief (synthesis without an LLM). Pure function over a profile."""
from __future__ import annotations

from typing import Any


def _nok(value: Any) -> str | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1e9:
        return f"{sign}NOK {v / 1e9:.1f} bn"
    if v >= 1e6:
        return f"{sign}NOK {v / 1e6:.1f} m"
    if v >= 1e3:
        return f"{sign}NOK {v / 1e3:.0f} k"
    return f"{sign}NOK {v:.0f}"


def _latest_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    dated = [r for r in records if (r.get("period") or {}).get("tilDato")]
    return max(dated, key=lambda r: r["period"]["tilDato"]) if dated else (records[-1] if records else None)


def company_brief(profile: dict[str, Any]) -> dict[str, Any]:
    """Sentences, each with its source; unknowns listed with what was checked. Never fills a missing value."""
    ev = profile.get("evidence") or {}
    sentences: list[dict[str, Any]] = []
    unknowns: list[dict[str, Any]] = []

    def add(text: str, record: dict[str, Any] | None, url: str | None = None) -> None:
        record = record or {}
        sentences.append({"text": text, "source_url": url or record.get("source_url"), "retrieved_at": record.get("retrieved_at")})

    name = profile.get("name") or profile.get("organisation_number")
    registry = ev.get("registry") or {}
    live = (ev.get("registry_live") or {}).get("value") or {}
    if registry.get("status") == "available":
        industry = profile.get("industry_label") or ((live.get("industry") or {}).get("beskrivelse"))
        place = profile.get("municipality") or ((live.get("business_address") or {}).get("kommune"))
        parts = [f"{name} (legal form {profile.get('legal_form') or 'not reported'})"]
        parts.append(f"is registered in {place.title()}" if place else "is registered")
        if industry and industry != "Uoppgitt":
            parts.append(f"with industry code '{industry}'")
        add(" ".join(parts) + ".", registry)
        employees = profile.get("employees")
        if employees:
            add(f"The registry reports {employees} employees.", registry)
        else:
            unknowns.append({"topic": "employees", "note": "Not reported in the registry (Brønnøysund publishes counts only from 5 employees); missing is not zero."})
        if profile.get("bankrupt") or profile.get("liquidating"):
            add("The registry flags the entity as bankrupt or under liquidation.", registry)
    else:
        unknowns.append({"topic": "registry", "note": "Organisation number not present in the registry snapshot."})

    fin = ev.get("financials") or {}
    records = ((fin.get("value") or {}).get("records") or []) if isinstance(fin.get("value"), dict) else []
    latest = _latest_record(records) if fin.get("status") == "available" else None
    if latest:
        year = ((latest.get("period") or {}).get("tilDato") or "")[:4]
        bits = []
        for label, key in (("revenue", "revenue"), ("operating result", "operating_result"), ("annual result", "annual_result"), ("equity", "equity")):
            text = _nok(latest.get(key))
            if text is not None:
                bits.append(f"{label} {text}")
        if bits:
            add(f"Latest filed accounts ({year}): " + ", ".join(bits) + ".", fin)
        if latest.get("revenue") is None:
            unknowns.append({"topic": "revenue", "note": f"No revenue line in the {year} filing; not converted to zero."})
    else:
        unknowns.append({"topic": "financials", "note": "No normalised annual account returned by Regnskapsregisteret."})

    roles_rec = ev.get("roles") or {}
    roles = ((roles_rec.get("value") or {}).get("roles") or []) if isinstance(roles_rec.get("value"), dict) else []
    active = [r for r in roles if not r.get("inactive")]
    ceo = next((r for r in active if r.get("role_code") == "DAGL"), None)
    chair = next((r for r in active if r.get("role_code") == "LEDE"), None)
    if ceo or chair:
        bits = []
        if ceo:
            bits.append(f"managing director {ceo.get('name')}")
        if chair:
            bits.append(f"board chair {chair.get('name')}")
        add("Official roles: " + " and ".join(bits) + ".", roles_rec)
    elif roles_rec.get("status") == "available":
        unknowns.append({"topic": "leadership", "note": "No active managing director or board chair in the official role register."})

    loc_rec = ev.get("locations") or {}
    locations = ((loc_rec.get("value") or {}).get("locations") or []) if isinstance(loc_rec.get("value"), dict) else []
    if locations:
        places = sorted({str(((l.get("address") or {}).get("kommune") or "")).title() for l in locations} - {""})
        add(f"{len(locations)} registered workplace(s)" + (f" in {', '.join(places[:5])}" if places else "") + ".", loc_rec)

    claims = profile.get("external_claims") or []
    site = next((c for c in claims if c.get("field") == "official_website" and c.get("availability") == "available"), None)
    if site:
        how = "found from its own domain and proven on the site" if "discovery" in str(site.get("method")) else "listed in the registry and verified"
        add(f"Official website {site.get('value')} ({how}: {site.get('identity_reason', '').split(';')[0]}).", site, site.get("source_url"))
        socials = sorted({c["field"] for c in claims if c.get("availability") == "available" and c.get("field") in {"facebook", "instagram", "linkedin", "youtube", "x", "tiktok"}})
        if socials:
            add("Company-owned profiles linked from the verified site: " + ", ".join(socials) + ".", site, site.get("source_url"))
    else:
        missing = next((c for c in claims if c.get("field") == "official_website"), {})
        unknowns.append({"topic": "website", "note": f"No website could be tied to this exact entity ({missing.get('availability', 'not_available')}); checked: " + "; ".join(missing.get("checked") or ["registry website field"])})

    jobs = [c for c in claims if c.get("field") == "job_postings" and c.get("availability") == "available"]
    if jobs:
        titles = "; ".join(str((c.get("value") or {}).get("title")) for c in jobs[:3])
        add(f"Hiring: {len(jobs)} active NAV vacancy(ies) under this org number or its workplaces, e.g. {titles}.", None, jobs[0].get("source_url"))
    else:
        unknowns.append({"topic": "hiring", "note": "No active NAV vacancy under this org number or its registered workplaces in the feed window; other job boards not checked."})

    return {"sentences": sentences, "unknowns": unknowns, "method": "deterministic_cited_brief_v1", "llm": False}

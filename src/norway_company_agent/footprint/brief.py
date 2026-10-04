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

    org = str(profile.get("organisation_number") or "")
    registry_page = f"https://virksomhet.brreg.no/nb/oppslag/enheter/{org}"

    def add(text: str, record: dict[str, Any] | None, url: str | None = None, verify: str | None = None) -> None:
        record = record or {}
        sentence = {"text": text, "source_url": url or record.get("source_url"), "retrieved_at": record.get("retrieved_at")}
        if verify or record.get("verify_url"):
            sentence["verify_url"] = verify or record.get("verify_url")  # human-readable page for the same fact
        sentences.append(sentence)

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
        founded = str(((registry.get("value") or {}) if isinstance(registry.get("value"), dict) else {}).get("stiftelsesdato") or "")[:10]
        add(" ".join(parts) + "." + (f" Founded {founded}." if founded else ""), registry, verify=registry_page)
        employees = profile.get("employees")
        if employees:
            add(f"The registry reports {employees} employees.", registry)
        else:
            unknowns.append({"topic": "employees", "note": "Not reported in the registry (Brønnøysund publishes counts only from 5 employees); missing is not zero."})
        if profile.get("bankrupt") or profile.get("liquidating"):
            add("The registry flags the entity as bankrupt or under liquidation.", registry)
        activity_lines = live.get("activity") or []
        if isinstance(activity_lines, list) and any(str(x).strip() for x in activity_lines):
            text = " ".join(str(x).strip() for x in activity_lines if str(x).strip())[:300]
            add(f"Registered activity (the company's own statement to the registry, in Norwegian): \"{text}\"", ev.get("registry_live"))
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
        dated = sorted((r for r in records if (r.get("period") or {}).get("tilDato")), key=lambda r: r["period"]["tilDato"], reverse=True)
        if len(dated) >= 2:
            prev = dated[1]
            prev_year = (prev["period"]["tilDato"] or "")[:4]
            changes = []
            for label, key in (("revenue", "revenue"), ("annual result", "annual_result"), ("equity", "equity")):
                a, b = prev.get(key), latest.get(key)
                if a is not None and b is not None:
                    pct = ""
                    if a > 0 and b >= 0:  # no % across zero or from a loss
                        ratio = (b - a) / a * 100
                        if round(ratio) == 0:
                            pct = " (about unchanged)"
                        elif a < 500_000:
                            pct = " (from a small base)"  # a percentage from a tiny base reads as a signal it is not
                        else:
                            pct = f" ({ratio:+.0f}%)"
                    changes.append(f"{label} {_nok(a)} → {_nok(b)}{pct}")
            if changes:
                add(f"Change {prev_year}→{year}: " + "; ".join(changes) + ".", fin)
        if latest.get("revenue") is None:
            unknowns.append({"topic": "revenue", "note": f"No revenue line in the {year} filing; not converted to zero."})
    elif fin.get("status") == "blocked":
        unknowns.append({"topic": "financials", "note": "Annual accounts not requested in this run: " + str(fin.get("note") or "request budget")})
    else:
        unknowns.append({"topic": "financials", "note": "No normalised annual account returned by Regnskapsregisteret."})

    roles_rec = ev.get("roles") or {}
    roles = ((roles_rec.get("value") or {}).get("roles") or []) if isinstance(roles_rec.get("value"), dict) else []
    active = [r for r in roles if not r.get("inactive")]
    ceo = next((r for r in active if r.get("role_code") == "DAGL"), None)
    chair = next((r for r in active if r.get("role_code") == "LEDE"), None)

    def since(role: dict[str, Any]) -> str:
        return f" (registered {str(role.get('last_changed'))[:10]})" if role.get("last_changed") else ""

    if ceo or chair:
        bits = []
        if ceo:
            bits.append(f"managing director {ceo.get('name')}{since(ceo)}")
        if chair:
            bits.append(f"board chair {chair.get('name')}{since(chair)}")
        members = sum(1 for r in active if r.get("role_code") == "MEDL")
        tail = f"; {members} other board member{'s' if members != 1 else ''}" if members else ""
        add("Official roles: " + " and ".join(bits) + tail + ".", roles_rec, verify=registry_page)
    elif roles_rec.get("status") == "available":
        unknowns.append({"topic": "leadership", "note": "No active managing director or board chair in the official role register."})

    auditor = next((r for r in active if r.get("role_code") == "REVI"), None)
    if auditor:
        ref = f" ({auditor.get('organisation_number')})" if auditor.get("organisation_number") else ""
        add(f"Auditor: {auditor.get('name')}{ref}.", roles_rec, verify=registry_page)

    group_rec = ev.get("group") or {}
    gval = group_rec.get("value") if isinstance(group_rec.get("value"), dict) else None
    if group_rec.get("status") == "available" and gval:
        nodes: list[dict[str, Any]] = []

        def walk(node: dict[str, Any]) -> None:
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    nodes.append(child)
                    walk(child)

        walk(gval)
        me = next((n for n in nodes if str(n.get("organisasjonsnummer")) == org), None)
        if me and me.get("parentNavn"):
            share = f" {me.get('grunnlag')}" if me.get("grunnlag") else ""
            date = f" since {me.get('dato')}" if me.get("dato") else ""
            top = f"; group top: {gval.get('navn')} ({gval.get('organisasjonsnummer')})" if str(gval.get("organisasjonsnummer")) != str(me.get("parentOrganisasjonsnummer")) else ""
            add(f"Owned{share} by {me.get('parentNavn')} ({me.get('parentOrganisasjonsnummer')}){date}{top}.", group_rec, verify=registry_page)
        elif str(gval.get("organisasjonsnummer")) == org:
            direct = [n for n in nodes if str(n.get("parentOrganisasjonsnummer")) == org]
            add(f"Parent of a registered group with {len(direct)} subsidiar{'ies' if len(direct) != 1 else 'y'}"
                + (f", e.g. {', '.join(str(n.get('navn')) for n in direct[:3])}" if direct else "") + ".", group_rec, verify=registry_page)

    loc_rec = ev.get("locations") or {}
    locations = ((loc_rec.get("value") or {}).get("locations") or []) if isinstance(loc_rec.get("value"), dict) else []
    if locations:
        places = sorted({str(((l.get("address") or {}).get("kommune") or "")).title() for l in locations} - {""})
        add(f"{len(locations)} registered workplace{'s' if len(locations) != 1 else ''}" + (f" in {', '.join(places[:5])}" if places else "") + ".", loc_rec, verify=registry_page)

    claims = profile.get("external_claims") or []
    selfdesc = next((c for c in claims if c.get("field") == "self_description" and c.get("availability") == "available"), None)
    if selfdesc:
        add(f"In its own words (company website): \"{selfdesc['value'][:220]}\"", selfdesc, selfdesc.get("source_url"))
    site = next((c for c in claims if c.get("field") == "official_website" and c.get("availability") == "available"), None)
    if site:
        how = "found from its own domain and proven on the site" if "discovery" in str(site.get("method")) else "listed in the registry and verified"
        add(f"Official website {site.get('value')} ({how}: {site.get('identity_reason', '').split(';')[0]}).", site, site.get("source_url"))
        socials = sorted({(c["field"], c.get("value")) for c in claims if c.get("availability") == "available" and c.get("field") in {"facebook", "instagram", "linkedin", "youtube", "x", "tiktok"}})
        if socials:
            add("Company-owned profiles linked from the verified site: " + ", ".join(f"{p} ({u})" for p, u in socials[:6]) + ".", site, site.get("source_url"))
    else:
        missing = next((c for c in claims if c.get("field") == "official_website"), {})
        declared = str(profile.get("website") or "").strip()
        lead = (f"The registry lists {declared}, but that site does not show this exact entity (it may be a group or brand site), so it is not published"
                if declared and missing.get("availability") == "ambiguous" else "No website could be tied to this exact entity")
        unknowns.append({"topic": "website", "note": f"{lead} ({missing.get('availability', 'not_available')}); checked: " + "; ".join(missing.get("checked") or ["registry website field"])})

    activity = [c for c in claims if c.get("field") == "dated_activity" and c.get("availability") == "available"]
    if activity:
        latest = activity[0]
        n = len(activity)
        add(f"Dated activity on the company's own site: {n} item{'s' if n != 1 else ''}; latest {latest['value'].get('date')} — '{latest['value'].get('title')}'.", latest, latest.get("source_url"))
    jobs = [c for c in claims if c.get("field") == "job_postings" and c.get("availability") == "available"]
    if jobs:
        titles = "; ".join(str((c.get("value") or {}).get("title")) for c in jobs[:3])
        n = len(jobs)
        add(f"Hiring: {n} active NAV vacanc{'ies' if n != 1 else 'y'} under this org number or its workplaces, e.g. {titles}.", jobs[0], jobs[0].get("source_url"))
    else:
        state = next((c.get("availability") for c in claims if c.get("field") == "job_postings"), "not_available")
        if state in {"failed", "blocked"}:
            unknowns.append({"topic": "hiring", "note": f"The NAV vacancy feed was not read in this run ({state}); hiring is unknown, not zero."})
        else:
            unknowns.append({"topic": "hiring", "note": "No active NAV vacancy under this org number or its registered workplaces in the feed window; other job boards not checked."})

    refresh = profile.get("refresh") or {}
    if refresh.get("compared"):
        changed = refresh.get("changes") or []
        since = f"the previous run ({refresh.get('previous_run_id') or 'earlier snapshot'})"
        if changed:
            def short(value: Any) -> str:
                text = value if isinstance(value, (str, int, float)) or value is None else f"{len(value)} item(s)" if isinstance(value, list) else "changed"
                return str(text)[:60]
            listed = "; ".join(f"{c['field']}: {short(c.get('old_value'))} → {short(c.get('new_value'))}" for c in changed[:3])
            add(f"Since {since}: {len(changed)} material change{'s' if len(changed) != 1 else ''} — {listed}.", {"source_url": changed[0].get("source_url"), "retrieved_at": changed[0].get("retrieved_at")})
        else:
            add(f"No material change since {since} in the fields both runs read.", registry)
        if refresh.get("not_compared"):
            unknowns.append({"topic": "refresh", "note": "Not compared with the previous run because one run could not read them: " + ", ".join(refresh["not_compared"])})

    return {"sentences": sentences, "unknowns": unknowns, "method": "deterministic_cited_brief_v2", "llm": False}

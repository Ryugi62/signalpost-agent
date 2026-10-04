"""v2 brief: cited dates for activity/hiring, founding date, group parent, auditor, plain plurals, small-base changes, verify links."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from norway_company_agent.footprint.brief import company_brief  # noqa: E402


def _profile(**evidence):
    base = {"registry": {"status": "available", "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv", "retrieved_at": "t0",
                         "value": {"stiftelsesdato": "2009-01-19"}}}
    base.update(evidence)
    return {"organisation_number": "993732990", "name": "FORUSVEIEN 31 - HOTELL AS", "legal_form": "AS", "evidence": base, "external_claims": []}


def _texts(profile):
    return " ".join(s["text"] for s in company_brief(profile)["sentences"])


def test_founding_date_and_verify_link():
    brief = company_brief(_profile())
    assert "Founded 2009-01-19" in brief["sentences"][0]["text"]
    assert brief["sentences"][0]["verify_url"] == "https://virksomhet.brreg.no/nb/oppslag/enheter/993732990"


def test_group_parent_sentence():
    group = {"status": "available", "source_url": "https://data.brreg.no/enhetsregisteret/api/konsernstruktur/993732990", "retrieved_at": "t1",
             "value": {"navn": "FORUS HOLDCO AS", "organisasjonsnummer": "928176541", "children": [
                 {"organisasjonsnummer": "993732990", "navn": "FORUSVEIEN 31 - HOTELL AS", "grunnlag": "100%", "dato": "2023-11-29",
                  "parentNavn": "FORUS HOLDCO AS", "parentOrganisasjonsnummer": "928176541"}]}}
    texts = _texts(_profile(group=group))
    assert "Owned 100% by FORUS HOLDCO AS (928176541) since 2023-11-29" in texts


def test_group_top_parent_sentence():
    group = {"status": "available", "source_url": "g", "value": {"navn": "FORUSVEIEN 31 - HOTELL AS", "organisasjonsnummer": "993732990", "children": [
        {"organisasjonsnummer": "1", "navn": "A AS", "parentOrganisasjonsnummer": "993732990"},
        {"organisasjonsnummer": "2", "navn": "B AS", "parentOrganisasjonsnummer": "993732990"}]}}
    assert "Parent of a registered group with 2 subsidiaries" in _texts(_profile(group=group))


def test_roles_with_dates_and_auditor():
    roles = {"status": "available", "source_url": "bulk", "retrieved_at": "t2", "value": {"roles": [
        {"name": "Rasmus Haugland", "role_code": "DAGL", "last_changed": "2011-10-15", "inactive": False},
        {"name": "Endre Haugland", "role_code": "LEDE", "last_changed": "2022-01-19", "inactive": False},
        {"name": "A", "role_code": "MEDL", "inactive": False}, {"name": "B", "role_code": "MEDL", "inactive": False},
        {"name": "REVISJON AS", "organisation_number": "999999999", "role_code": "REVI", "inactive": False}]}}
    texts = _texts(_profile(roles=roles))
    assert "managing director Rasmus Haugland (registered 2011-10-15)" in texts
    assert "board chair Endre Haugland (registered 2022-01-19)" in texts
    assert "2 other board members" in texts
    assert "Auditor: REVISJON AS (999999999)." in texts


def test_activity_and_hiring_carry_retrieval_time_and_plurals():
    claims = [
        {"field": "dated_activity", "availability": "available", "source_url": "https://foo.no/feed/", "retrieved_at": "t3",
         "value": {"date": "2026-09-30", "title": "Ny avtale"}},
        {"field": "job_postings", "availability": "available", "source_url": "https://arbeidsplassen.nav.no/x", "retrieved_at": "t4",
         "value": {"title": "Kokk"}},
    ]
    profile = _profile()
    profile["external_claims"] = claims
    sentences = company_brief(profile)["sentences"]
    act = next(s for s in sentences if "Dated activity" in s["text"])
    job = next(s for s in sentences if "Hiring" in s["text"])
    assert act["retrieved_at"] == "t3" and job["retrieved_at"] == "t4"
    assert "1 item;" in act["text"] and "1 active NAV vacancy " in job["text"]


def test_small_base_and_flat_changes():
    fin = {"status": "available", "source_url": "f", "value": {"records": [
        {"period": {"tilDato": "2025-12-31"}, "revenue": 1_400_000.0, "equity": 1_000_400.0},
        {"period": {"tilDato": "2024-12-31"}, "revenue": 67_000.0, "equity": 1_000_000.0}]}}
    texts = _texts(_profile(financials=fin))
    assert "revenue NOK 67 k → NOK 1.4 m (from a small base)" in texts
    assert "equity NOK 1.0 m → NOK 1.0 m (about unchanged)" in texts
    assert "%" not in texts.split("Change")[1]


def test_social_profiles_listed_with_urls():
    profile = _profile()
    profile["external_claims"] = [
        {"field": "official_website", "availability": "available", "value": "https://foo.no/", "source_url": "https://foo.no/", "method": "x", "identity_reason": "org"},
        {"field": "facebook", "availability": "available", "value": "https://facebook.com/foo"},
    ]
    assert "facebook (https://facebook.com/foo)" in _texts(profile)


def test_refresh_sentence_and_unread_jobs():
    profile = _profile()
    profile["refresh"] = {"compared": True, "previous_run_id": "r1", "changes": [
        {"field": "registry.employees", "old_value": 3, "new_value": 5, "source_url": "https://data.brreg.no/x", "retrieved_at": "t9"}], "not_compared": ["financials.records"]}
    profile["external_claims"] = [{"field": "job_postings", "availability": "failed"}]
    brief = company_brief(profile)
    texts = " ".join(s["text"] for s in brief["sentences"])
    assert "Since the previous run (r1): 1 material change — registry.employees: 3 → 5." in texts
    notes = {u["topic"]: u["note"] for u in brief["unknowns"]}
    assert "not read in this run (failed)" in notes["hiring"] and "financials.records" in notes["refresh"]

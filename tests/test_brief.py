import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from norway_company_agent.footprint.brief import company_brief  # noqa: E402


def test_brief_cites_sources_and_lists_unknowns():
    profile = {
        "organisation_number": "123456785", "name": "FOO AS", "legal_form": "AS", "municipality": "OSLO",
        "industry_label": "Rørleggerarbeid", "employees": None,
        "evidence": {
            "registry": {"status": "available", "source_url": "https://data.brreg.no/x", "retrieved_at": "t"},
            "financials": {"status": "available", "source_url": "https://data.brreg.no/regnskap", "value": {"records": [
                {"period": {"tilDato": "2024-12-31"}, "revenue": None, "operating_result": -4279.0, "annual_result": -4279.0, "equity": 5000.0}]}},
            "roles": {"status": "available", "source_url": "https://data.brreg.no/roller", "value": {"roles": [
                {"name": "Kari Nordmann", "role_code": "DAGL", "inactive": False}]}},
        },
        "external_claims": [{"field": "official_website", "availability": "not_available", "checked": ["foo.no: no_dns"]},
                            {"field": "job_postings", "availability": "not_available"}],
    }
    brief = company_brief(profile)
    texts = " ".join(s["text"] for s in brief["sentences"])
    assert "FOO AS (legal form AS) is registered in Oslo" in texts
    assert "-NOK 4 k" in texts and "revenue" not in texts.split("Latest filed accounts")[1].split(".")[0]
    assert all(s["source_url"] for s in brief["sentences"])
    topics = {u["topic"] for u in brief["unknowns"]}
    assert {"employees", "revenue", "website", "hiring"} <= topics
    assert brief["llm"] is False


def test_brief_year_over_year_change():
    profile = {"organisation_number": "1", "name": "X AS", "legal_form": "AS", "evidence": {
        "registry": {"status": "available", "source_url": "u"},
        "financials": {"status": "available", "source_url": "f", "value": {"records": [
            {"period": {"tilDato": "2025-12-31"}, "revenue": 2_000_000.0, "annual_result": 100_000.0},
            {"period": {"tilDato": "2024-12-31"}, "revenue": 1_000_000.0, "annual_result": None}]}}},
        "external_claims": []}
    texts = " ".join(s["text"] for s in company_brief(profile)["sentences"])
    assert "Change 2024→2025: revenue NOK 1.0 m → NOK 2.0 m (+100%)." in texts


def test_no_percentage_across_zero():
    profile = {"organisation_number": "1", "name": "X AS", "legal_form": "AS", "evidence": {
        "registry": {"status": "available", "source_url": "u"},
        "financials": {"status": "available", "source_url": "f", "value": {"records": [
            {"period": {"tilDato": "2025-12-31"}, "annual_result": 2_000.0},
            {"period": {"tilDato": "2024-12-31"}, "annual_result": -36.0}]}}},
        "external_claims": []}
    texts = " ".join(s["text"] for s in company_brief(profile)["sentences"])
    assert "annual result -NOK 36 → NOK 2 k." in texts


def test_brief_registered_activity_and_budget_unknown():
    profile = {"organisation_number": "1", "name": "X AS", "legal_form": "AS", "evidence": {
        "registry": {"status": "available", "source_url": "u"},
        "registry_live": {"status": "available", "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/1", "retrieved_at": "t",
                          "value": {"activity": ["Drift av restaurant og kafé.", "Catering."]}},
        "financials": {"status": "blocked", "source_url": "f", "note": "Not requested: the run's outbound request budget (policy)"}},
        "external_claims": []}
    brief = company_brief(profile)
    act = [s for s in brief["sentences"] if s["text"].startswith("Registered activity")]
    assert act and "Drift av restaurant og kafé. Catering." in act[0]["text"]
    assert act[0]["source_url"].endswith("/enheter/1")
    fin = next(u for u in brief["unknowns"] if u["topic"] == "financials")
    assert "request budget" in fin["note"]

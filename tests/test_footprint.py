import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.footprint.domain import (  # noqa: E402
    domain_candidates,
    identity_proof,
    match_jobs_to_orgs,
    name_key,
    parse_wikidata_bindings,
    flatten_external_claims,
)


def test_ac1_domain_candidates():
    c = domain_candidates("SANDNES ELEKTRISKE AS")
    assert "sandneselektriske.no" in c
    assert "sandnes-elektriske.no" in c
    assert not any("as." in x or x.startswith("as") for x in c)
    assert domain_candidates("GJØVIK TANNLEGEKONTOR AS")[0] == "gjoviktannlegekontor.no"
    assert domain_candidates("AS") == []


def test_ac2_org_proof():
    profile = {"organisation_number": "810034882", "name": "SANDNES ELEKTRISKE AS"}
    assert identity_proof(profile, ["Kontakt oss. Org.nr: 810 034 882 MVA"])["proof"] == "org"
    assert identity_proof(profile, ["Org.nr: 999 888 777"])["proof"] == "none"
    assert identity_proof(profile, ["NO810.034.882MVA"])["proof"] == "org"


def test_ac3_contact_proof():
    profile = {
        "organisation_number": "810034882",
        "name": "SANDNES ELEKTRISKE AS",
        "registry": {"postcode": "4313", "street": "Kvellandstrand 4", "phone": "+47 51 66 00 00"},
    }
    page = "Sandnes Elektriske AS – Kvellandstrand 4, 4313 Sandnes"
    assert identity_proof(profile, [page])["proof"] == "contact"
    assert identity_proof(profile, ["Sandnes Elektriske – vi leverer strøm"])["proof"] == "none"
    assert identity_proof(profile, ["Sandnes Elektriske tlf 51 66 00 00"])["proof"] == "contact"
    # single generic token must never pass on name+phone alone without org proof? it may pass with phone
    generic = {"organisation_number": "123456789", "name": "ADMINISTRATOR AS", "registry": {"postcode": "0150", "street": "Gate 1"}}
    assert identity_proof(generic, ["Administrator software for everyone"])["proof"] == "none"


def test_ac4_jobs_subunit_attribution():
    orgs = {"111111111": {"subunits": ["222222222"]}, "333333333": {"subunits": []}}
    details = [
        {"uuid": "a", "employer": {"orgnr": "222222222", "name": "X"}, "title": "T"},
        {"uuid": "b", "employer": {"orgnr": "999999999", "name": "Y"}, "title": "T"},
        {"uuid": "c", "employer": {"orgnr": "333333333", "name": "Z"}, "title": "T"},
    ]
    m = match_jobs_to_orgs(details, orgs)
    assert [d["uuid"] for d in m["111111111"]] == ["a"]
    assert [d["uuid"] for d in m["333333333"]] == ["c"]
    assert "999999999" not in m


def test_name_key():
    assert name_key("Arendal Båtskade Service As") == name_key("ARENDAL BÅTSKADE SERVICE AS")
    assert name_key("Foo AS") == "foo"


def test_ac5_wikidata_parse():
    bindings = [
        {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "org": {"value": "938702675"},
         "website": {"value": "https://www.afgruppen.no/"}, "facebook": {"value": "afgruppen"}},
    ]
    out = parse_wikidata_bindings(bindings)
    claims = out["938702675"]
    fields = {c["field"]: c for c in claims}
    assert fields["official_website"]["value"] == "https://www.afgruppen.no/"
    assert fields["facebook"]["value"] == "https://www.facebook.com/afgruppen"
    assert fields["facebook"]["source_url"] == "https://www.wikidata.org/wiki/Q1"


def test_ac6_flatten_claims_explicit_states():
    profile = {"organisation_number": "1", "evidence": {
        "jobs": {"status": "not_found", "source_url": "u", "retrieved_at": "t"},
    }}
    claims = flatten_external_claims(profile)
    states = {c["field"]: c["availability"] for c in claims}
    assert states["job_postings"] == "not_available"
    assert states["official_website"] in {"not_available", "failed", "ambiguous"}


def test_redirect_off_candidate_is_rejected(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: True)

    def fake_fetch(url, **kwargs):
        return ({"status": "available", "source_url": "https://www.vvseksperten.no/x", "value": {
            "final_url": "https://www.vvseksperten.no/rorlegger/agn-ror-as", "registered_domain": "vvseksperten.no",
            "title": "AGN Rør AS", "identity_text_excerpt": "AGN Rør AS tlf 61 22 33 44", "pages": [], "social_links": []}},
            {"requests": 2, "bytes": 10, "latencies_ms": [1]})

    monkeypatch.setattr(fio, "fetch_website", fake_fetch)
    profile = {"organisation_number": "123456785", "name": "AGN RØR AS",
               "evidence": {"registry_live": {"value": {"phone": "61223344", "business_address": {"adresse": ["Vei 1"], "postnummer": "2600"}}}}}
    found, discovery, _ = fio.discover_website(profile)
    assert found is None
    assert any(a["result"] == "redirected_off_candidate" for a in discovery["value"]["attempts"])


def test_brand_and_alt_spelling_candidates():
    c = domain_candidates("ÅSANE BYGG AS", limit=6, brand_names=["HUSKESTUA BARNEHAGE"])
    assert c[:2] == ["asanebygg.no", "asane-bygg.no"]
    assert "huskestuabarnehage.no" in c
    assert "aasanebygg.no" in c


def test_redirect_to_brand_root_with_sole_org_is_accepted(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: True)

    def fake_fetch(url, **kwargs):
        return ({"status": "available", "source_url": "https://www.tidesnorway.com/", "value": {
            "final_url": "https://www.tidesnorway.com/", "registered_domain": "tidesnorway.com",
            "title": "Tides Norway", "identity_text_excerpt": "Tides AS · Org.nr 912 345 678", "pages": [], "social_links": []}},
            {"requests": 2, "bytes": 10, "latencies_ms": [1]})

    monkeypatch.setattr(fio, "fetch_website", fake_fetch)
    profile = {"organisation_number": "912345678", "name": "TIDES AS", "evidence": {}}
    found, _, _ = fio.discover_website(profile)
    assert found is not None

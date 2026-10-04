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
    from norway_company_agent.footprint.domain import address_key
    unique = {"phone": {"51660000": 1}, "address": {address_key("Kvellandstrand 4", "4313"): 1}}
    page = "Sandnes Elektriske AS – Kvellandstrand 4, 4313 Sandnes"
    assert identity_proof(profile, [page], collisions=unique)["proof"] == "contact"
    assert identity_proof(profile, [page])["proof"] == "none"  # fail closed without registry-wide counts
    assert identity_proof(profile, ["Sandnes Elektriske – vi leverer strøm"], collisions=unique)["proof"] == "none"
    assert identity_proof(profile, ["Sandnes Elektriske tlf 51 66 00 00"], collisions=unique)["proof"] == "contact"
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


def test_email_domain_candidate():
    from norway_company_agent.footprint.domain import email_domain_candidate
    assert email_domain_candidate("post@kiship.no", {"kiship.no": 1}) == "kiship.no"
    assert email_domain_candidate("post@kiship.no") is None  # fail closed without counts
    assert email_domain_candidate("a@parent.no", {"parent.no": 2}) is None
    assert email_domain_candidate("ola@gmail.com") is None
    assert email_domain_candidate("styret@usbl.no", {"usbl.no": 899}) is None
    assert email_domain_candidate("x@firma.no", {"firma.no": 1}) == "firma.no"
    assert email_domain_candidate("") is None


def test_directory_page_and_shared_phone_rejected():
    profile = {"organisation_number": "810034882", "name": "SANDNES ELEKTRISKE AS",
               "registry": {"postcode": "4313", "street": "Kvellandstrand 4", "phone": "51660000"}}
    directory = "Sandnes Elektriske AS 810 034 882 · Bergen Rør AS 912 345 678"
    assert identity_proof(profile, [directory])["proof"] == "none"
    shared = {"phone": {"51660000": 4}, "address": {}}
    assert identity_proof(profile, ["Sandnes Elektriske tlf 51 66 00 00"], collisions=shared)["proof"] == "none"
    unique = {"phone": {"51660000": 1}, "address": {}}
    out = identity_proof(profile, ["Sandnes Elektriske tlf 51 66 00 00"], collisions=unique)
    assert out["proof"] == "contact" and "51 66" not in out["snippet"] and "withheld" in out["snippet"]


def test_absent_org_still_gets_profile(tmp_path):
    import gzip
    from norway_company_agent.batch import profiles_from_bulk
    bulk = tmp_path / "b.csv"
    with gzip.open(bulk, "wt", encoding="utf-8") as h:
        h.write('"organisasjonsnummer";"navn";"organisasjonsform.kode"\n"123456785";"FOO AS";"AS"\n')
    profiles, meta = profiles_from_bulk(bulk, ["123456785", "987654321"])
    assert [p["organisation_number"] for p in profiles] == ["123456785", "987654321"]
    assert profiles[1]["evidence"]["registry"]["status"] == "not_found"
    assert meta["absent_from_snapshot"] == ["987654321"]


def test_subsidiary_qualifier_requires_org_proof(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: True)

    def fake_fetch(url, **kwargs):
        return ({"status": "available", "source_url": "https://www.enry.com/", "value": {
            "final_url": "https://www.enry.com/", "registered_domain": "enry.com",
            "title": "Enry Norway – cleaning", "identity_text_excerpt": "Enry Norway AS, Storgata 1, 0155 Oslo tlf 22 11 22 33",
            "pages": [], "social_links": []}}, {"requests": 2, "bytes": 10, "latencies_ms": [1]})

    monkeypatch.setattr(fio, "fetch_website", fake_fetch)
    profile = {"organisation_number": "921183623", "name": "ENRY NORWAY AS",
               "evidence": {"registry": {"value": {"epostadresse": "post@enry.com"}},
                            "registry_live": {"value": {"phone": "22112233", "business_address": {"adresse": ["Storgata 1"], "postnummer": "0155"}}}}}
    found, discovery, _ = fio.discover_website(profile, collisions={"email_domain": {"enry.com": 1}, "phone": {"22112233": 1}, "address": {}})
    assert found is None
    assert any(a["result"] == "brand_or_parent_site" for a in discovery["value"]["attempts"])


def test_snippet_masks_email():
    profile = {"organisation_number": "810034882", "name": "X AS"}
    out = identity_proof(profile, ["kontakt ola.nordmann@firma.no Org.nr 810 034 882"])
    assert out["proof"] == "org" and "@" not in out["snippet"]


def test_other_org_in_odd_grouping_blocks_org_proof():
    profile = {"organisation_number": "892469172", "name": "FJORDSAILING AS"}
    assert identity_proof(profile, ["Org.no: 995 91 6193 MVA Org.no. 892 46 9172 MVA"])["proof"] == "none"


def test_wikidata_socials_need_corroboration():
    wd = {"status": "available", "value": {"claims": [
        {"field": "official_website", "value": "https://www.foo.no/", "source_url": "https://www.wikidata.org/wiki/Q1"},
        {"field": "facebook", "value": "https://www.facebook.com/foo", "source_url": "https://www.wikidata.org/wiki/Q1"}]}}
    bare = flatten_external_claims({"evidence": {"wikidata": wd}})
    assert {c["field"]: c["availability"] for c in bare}["facebook"] == "ambiguous"
    site = {"status": "available", "source_url": "https://foo.no/", "value": {"final_url": "https://foo.no/",
            "identity_assessment": {"publishable": True, "reasons": ["x"]}, "social_links": []}}
    ok = flatten_external_claims({"evidence": {"wikidata": wd, "website": site}})
    assert {c["field"]: c["availability"] for c in ok}["facebook"] == "available"


def test_short_single_token_needs_org_number():
    from norway_company_agent.identity import assess_website_identity
    profile = {"organisation_number": "123456785", "name": "LEK 3 AS", "evidence": {"website": {"value": {
        "final_url": "https://www.ringo.no/", "title": "Ringo leker", "main_text_excerpt": "Leker for alle " * 20}}}}
    assert assess_website_identity(profile)["publishable"] is False


def test_financial_records_latest_first():
    from norway_company_agent.official import normalize_financials
    body = [{"regnskapsperiode": {"tilDato": "2023-12-31"}}, {"regnskapsperiode": {"tilDato": "2025-12-31"}}]
    assert normalize_financials(body)["records"][0]["period"]["tilDato"] == "2025-12-31"

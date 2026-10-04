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
    assert any(a["result"] in {"brand_or_parent_site", "none"} for a in discovery["value"]["attempts"])


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


def test_flatten_with_jobs_and_wikidata_does_not_crash():
    jobs = {"status": "available", "retrieved_at": "t", "value": {"items": [{"title": "T", "url": "u", "published": "2026-10-01"}]}}
    wd = {"status": "available", "value": {"claims": [{"field": "facebook", "value": "https://www.facebook.com/x", "source_url": "w"}]}}
    claims = flatten_external_claims({"evidence": {"jobs": jobs, "wikidata": wd}})
    assert any(c["field"] == "job_postings" and c["availability"] == "available" for c in claims)


def test_email_domain_needs_org_or_unique_contact(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: True)

    def fake_fetch(url, **kwargs):
        return ({"status": "available", "source_url": "https://personalpartner.no/", "value": {
            "final_url": "https://personalpartner.no/", "registered_domain": "personalpartner.no",
            "title": "Personal Partner – Carlbergveien 7", "identity_text_excerpt": "Besøk oss i Carlbergveien 7, 1526 Moss",
            "main_text_excerpt": "Vi leverer personell " * 20, "pages": [], "social_links": []}}, {"requests": 2, "bytes": 10, "latencies_ms": [1]})

    monkeypatch.setattr(fio, "fetch_website", fake_fetch)
    profile = {"organisation_number": "912345678", "name": "CARLBERGVEIEN 7 AS",
               "evidence": {"registry": {"value": {"epostadresse": "x@personalpartner.no"}},
                            "registry_live": {"value": {"business_address": {"adresse": ["Carlbergveien 7"], "postnummer": "1526"}}}}}
    from norway_company_agent.footprint.domain import address_key
    found, _, _ = fio.discover_website(profile, collisions={"email_domain": {"personalpartner.no": 1}, "phone": {},
                                                             "address": {address_key("Carlbergveien 7", "1526"): 2}})
    assert found is None


def test_dated_activity_extraction_and_claims():
    from bs4 import BeautifulSoup
    from norway_company_agent.website import _dated_activity
    html = '<article><h2><a href="/nyheter/a">Ny avtale med kommunen</a></h2><time datetime="2026-09-12">12. sep</time></article>'
    meta = {"json-ld": [{"@type": "NewsArticle", "headline": "Åpner ny avdeling", "datePublished": "2026-08-01T10:00:00+02:00", "url": "/n/b"}]}
    items = _dated_activity("https://foo.no/", BeautifulSoup(html, "lxml"), meta)
    assert [i["date"] for i in items] == ["2026-09-12", "2026-08-01"]
    assert items[0]["url"] == "https://foo.no/nyheter/a"
    site = {"status": "available", "source_url": "https://foo.no/", "retrieved_at": "t", "value": {"final_url": "https://foo.no/",
            "identity_assessment": {"publishable": True, "reasons": ["x"]}, "social_links": [], "dated_activity": items, "pages": []}}
    claims = flatten_external_claims({"name": "FOO AS", "evidence": {"website": site}})
    acts = [c for c in claims if c["field"] == "dated_activity"]
    assert len(acts) == 2 and acts[0]["effective_at"] == "2026-09-12" and acts[0]["availability"] == "available"


def test_seo_webpage_metadata_is_not_activity():
    from bs4 import BeautifulSoup
    from norway_company_agent.website import _dated_activity
    meta = {"json-ld": [{"@type": "Article", "headline": "Om oss", "datePublished": "2024-08-02", "url": "https://x.no/om-oss/#webpage"}]}
    html = '<title>Om oss</title><article><h2>Beskyttet: Intern</h2><time datetime="2026-01-01"></time></article>'
    assert _dated_activity("https://x.no/", BeautifulSoup(html, "lxml"), meta) == []


def test_role_mailbox_and_self_description_claims():
    site = {"status": "available", "source_url": "https://foo.no/", "retrieved_at": "t", "value": {"final_url": "https://www.foo.no/",
            "identity_assessment": {"publishable": True, "reasons": ["x"]}, "social_links": [], "pages": [],
            "description": "Foo AS leverer rørleggertjenester i hele Rogaland siden 1987.",
            "identity_text_excerpt": "post@foo.no ola.nordmann@foo.no info@gmail.com"}}
    claims = flatten_external_claims({"evidence": {"website": site}})
    emails = [c["value"] for c in claims if c["field"] == "contact_email"]
    assert emails == ["post@foo.no"]
    assert any(c["field"] == "self_description" for c in claims)


def test_dotcom_candidate_requires_org_proof(monkeypatch):
    from norway_company_agent.footprint import io as fio
    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: host.endswith(".com"))

    def fake_fetch(url, **kwargs):
        return ({"status": "available", "source_url": url, "value": {
            "final_url": "https://www.confecta.com/", "registered_domain": "confecta.com",
            "title": "Confecta", "identity_text_excerpt": "Confecta Norge tlf 22 33 44 55", "pages": [], "social_links": []}},
            {"requests": 2, "bytes": 10, "latencies_ms": [1]})
    monkeypatch.setattr(fio, "fetch_website", fake_fetch)
    profile = {"organisation_number": "912345678", "name": "CONFECTA AS",
               "evidence": {"registry_live": {"value": {"phone": "22334455", "business_address": {}}}}}
    found, _, _ = fio.discover_website(profile, collisions={"email_domain": {}, "phone": {"22334455": 1}, "address": {}})
    assert found is None


def test_ac17_registry_site_reused_without_new_request(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: False)

    def no_fetch(url, **kwargs):
        raise AssertionError("the registry-declared site was already fetched")

    monkeypatch.setattr(fio, "fetch_website", no_fetch)
    prior = {"status": "available", "source_url": "https://www.secpro.as/", "source_class": "registry_linked_company_website",
             "source_type": "registry_linked_company_website",
             "value": {"requested_url": "https://www.secpro.as/", "final_url": "https://www.secpro.as/", "registered_domain": "secpro.as",
                       "title": "SecPro", "identity_text_excerpt": "SecurityProducts AS · Org.nr 912 345 678", "pages": [], "social_links": [],
                       "identity_assessment": {"status": "related_or_uncertain", "publishable": False}}}
    profile = {"organisation_number": "912345678", "name": "SECURITYPRODUCTS AS", "evidence": {}}
    found, discovery, metrics = fio.discover_website(profile, prior_record=prior)
    assert found is not None and metrics["requests"] == 0
    assert found["source_class"] == "registry_linked_company_website"
    assert found["value"]["identity_assessment"]["publishable"] is True
    assert prior["value"]["identity_assessment"]["publishable"] is False  # input record not mutated


def test_ac17_registry_site_without_proof_stays_withheld(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: False)
    monkeypatch.setattr(fio, "_fetch_secondary_page", lambda url, **kw: (None, [], 1, 0, 0, "HTTP 404"))
    prior = {"status": "available", "source_url": "https://www.privatmegleren.no/",
             "value": {"requested_url": "https://www.privatmegleren.no/", "final_url": "https://privatmegleren.no/", "registered_domain": "privatmegleren.no",
                       "title": "PrivatMegleren", "identity_text_excerpt": "Bjørnefjorden eiendomsmegling", "pages": [], "social_links": []}}
    profile = {"organisation_number": "912345678", "name": "BJØRNEFJORDEN AS", "evidence": {}}
    found, _, _ = fio.discover_website(profile, prior_record=prior, collisions={"email_domain": {}, "phone": {}, "address": {}})
    assert found is None


def test_ac18_declared_extra_host_needs_org_number(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: host == "gaiaarkitekter.no")
    monkeypatch.setattr(fio, "_fetch_secondary_page", lambda url, **kw: (None, [], 1, 0, 0, "HTTP 404"))

    def fake_fetch(url, **kwargs):
        return ({"status": "available", "source_url": url, "value": {
            "final_url": "https://gaiaarkitekter.no/", "registered_domain": "gaiaarkitekter.no",
            "title": "Gaia Lista arkitekter", "identity_text_excerpt": "Gaia Lista AS tlf 22 33 44 55", "pages": [], "social_links": []}},
            {"requests": 2, "bytes": 10, "latencies_ms": [1]})

    monkeypatch.setattr(fio, "fetch_website", fake_fetch)
    profile = {"organisation_number": "912345678", "name": "GAIA LISTA AS",
               "evidence": {"registry_live": {"value": {"phone": "22334455", "business_address": {}}}}}
    found, discovery, _ = fio.discover_website(profile, extra_hosts=["gaiaarkitekter.no"],
                                               collisions={"email_domain": {}, "phone": {"22334455": 1}, "address": {}})
    assert found is None
    assert discovery["value"]["candidates"][0] == "gaiaarkitekter.no"


def test_ac19_homepage_first_secondary_pages():
    from norway_company_agent.footprint.io import secondary_pages_for
    decide = secondary_pages_for({"organisation_number": "810034882", "name": "SANDNES ELEKTRISKE AS"})
    assert decide({"title": "Parked domain", "final_url": "https://sandneselektriske.no/"}) == 0
    assert decide({"title": "Sandnes Elektriske – elektriker", "final_url": "https://sandneselektriske.no/"}) == 2
    assert decide({"identity_text_excerpt": "Org.nr 810 034 882", "final_url": "https://x.no/"}) == 1


def test_ac20_run_budget_stops_new_fetches(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: True)

    def no_fetch(url, **kwargs):
        raise AssertionError("budget said no")

    monkeypatch.setattr(fio, "fetch_website", no_fetch)
    found, discovery, metrics = fio.discover_website({"organisation_number": "912345678", "name": "FOO BAR AS", "evidence": {}}, can_spend=lambda: False)
    assert found is None and metrics["requests"] == 0
    assert discovery["value"]["attempts"][0]["result"] == "run_request_budget_exhausted"


def test_ac21_only_first_generated_candidate_is_fetched(monkeypatch):
    from norway_company_agent.footprint import io as fio

    monkeypatch.setattr(fio, "_resolves", lambda host, timeout=4.0: True)
    fetched = []

    def fake_fetch(url, **kwargs):
        fetched.append(url)
        return ({"status": "available", "source_url": url, "value": {"final_url": url, "registered_domain": url.split("/")[2],
                 "title": "Something else", "pages": [], "social_links": []}}, {"requests": 2, "bytes": 1, "latencies_ms": [1]})

    monkeypatch.setattr(fio, "fetch_website", fake_fetch)
    profile = {"organisation_number": "912345678", "name": "SANDNES ELEKTRISKE AS",
               "evidence": {"locations": {"value": {"locations": [{"name": "X", "website": "www.sandnes-el.no"}]}}}}
    monkeypatch.setattr(fio, "_fetch_secondary_page", lambda url, **kw: (None, [], 1, 0, 0, "HTTP 404"))
    fio.discover_website(profile, collisions={"email_domain": {}, "phone": {}, "address": {}})
    assert fetched == ["https://sandnes-el.no/", "https://sandneselektriske.no/"]

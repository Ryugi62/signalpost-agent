"""Fixes from the v2 mock review: honest states, group-site news, shared hosts, social roots, registry gate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from norway_company_agent.footprint.domain import _reg_domain, activity_allowed, flatten_external_claims  # noqa: E402


def _site(final_url, method="deterministic_name_org_evidence_v2", reasons=("all normalized legal-name tokens appear",), **extra):
    value = {"final_url": final_url, "registered_domain": _reg_domain(final_url), "pages": [], "social_links": [],
             "identity_assessment": {"publishable": True, "method": method, "reasons": list(reasons)}}
    value.update(extra)
    return {"status": "available", "source_url": final_url, "retrieved_at": "t", "value": value}


def test_group_site_news_is_not_attributed():
    item = {"title": "Hyr feirer 5 år", "date": "2026-06-04", "type": "feed_post", "url": "https://hyr.no/hyr-feirer-5-ar/", "method": "rss"}
    site = _site("https://hyr.no/", feed_activity={"feed_url": "https://hyr.no/feed/", "items": [item]})
    claims = flatten_external_claims({"name": "HYR BERGEN AS", "evidence": {"website": site}})
    acts = [c for c in claims if c["field"] == "dated_activity"]
    assert len(acts) == 1 and acts[0]["availability"] == "not_available" and "group or brand" in acts[0]["note"]
    assert activity_allowed(site["value"], "HYR AS")
    assert not activity_allowed(_site("https://plasman.com/")["value"], "PLASMAN AS")
    assert activity_allowed(_site("https://x.com/", reasons=("exact organisation number appears in homepage identity evidence",))["value"], "X AS")


def test_items_named_after_the_company_or_hosted_elsewhere_are_dropped():
    items = [{"title": "Fjøssystemer", "date": "2026-01-01", "url": "https://fjossystemer.no/", "method": "article-time"},
             {"title": "Omtale i avisa", "date": "2026-02-01", "url": "https://avisa.no/sak", "method": "json-ld"},
             {"title": "Nytt lager", "date": "2026-03-01", "url": "https://fjossystemer.no/nytt-lager", "method": "json-ld"}]
    site = _site("https://fjossystemer.no/", dated_activity=items)
    claims = flatten_external_claims({"name": "FJØSSYSTEMER AS", "evidence": {"website": site}})
    assert [c["value"]["title"] for c in claims if c["field"] == "dated_activity" and c["availability"] == "available"] == ["Nytt lager"]


def test_every_family_has_a_state_and_budget_stops_are_blocked():
    profile = {"name": "FOO AS", "evidence": {
        "website": {"status": "not_found", "source_url": "about:blank"},
        "website_discovery": {"status": "blocked", "value": None, "note": "Not requested: the run's outbound request budget (policy)"}}}
    claims = {c["field"]: c for c in flatten_external_claims(profile)}
    assert claims["official_website"]["availability"] == "blocked"
    for family in ("social_profiles", "dated_activity", "contact_email", "self_description", "job_postings"):
        assert family in claims
    assert claims["social_profiles"]["availability"] == "blocked"
    plain = {"name": "FOO AS", "evidence": {"website": {"status": "not_found"}, "website_discovery": {"status": "not_found", "value": {"attempts": []}}}}
    assert {c["field"]: c["availability"] for c in flatten_external_claims(plain)}["contact_email"] == "not_available"


def test_verified_site_without_profiles_states_it():
    claims = {c["field"]: c for c in flatten_external_claims({"name": "FOO AS", "evidence": {"website": _site("https://foo.no/")}})}
    assert claims["social_profiles"]["availability"] == "not_available"
    assert claims["contact_email"]["availability"] == "not_available"
    assert claims["self_description"]["availability"] == "not_available"


def test_shared_site_builder_hosts_keep_the_tenant():
    assert _reg_domain("https://foo.wixsite.com/home") == "foo.wixsite.com"
    assert _reg_domain("https://bar.wixsite.com/x") != _reg_domain("https://foo.wixsite.com/")
    assert _reg_domain("https://www.foo.no/x") == "foo.no"


def test_social_urls_are_profile_roots():
    from norway_company_agent.website import normalize_social_url
    assert normalize_social_url("https://www.facebook.com/fjossystemergruppen/events")["url"] == "https://facebook.com/fjossystemergruppen"
    assert normalize_social_url("https://www.instagram.com/foo_as/?hl=nb")["url"] == "https://instagram.com/foo_as"


def test_registry_gate_needs_a_sole_org_number_and_keeps_a_snippet():
    from norway_company_agent.identity import assess_website_identity
    def profile(text):
        return {"organisation_number": "912345678", "name": "ALFA BETA GAMMA AS", "evidence": {"website": {"value": {
            "title": "Konsernoversikt", "identity_text_excerpt": text, "main_text_excerpt": "", "pages": []}}}}
    group_page = assess_website_identity(profile("Selskaper: 912 345 678, 987 654 321, 923 456 789"))
    assert group_page["score"] < 1.0
    own = assess_website_identity(profile("Alfa Beta Gamma AS · Org.nr 912 345 678 · post@alfa.no"))
    assert own["score"] == 1.0 and "912 345 678" in own["proof_snippet"] and "@" not in own["proof_snippet"]


def test_bulk_snapshot_plain_or_gzip(tmp_path):
    import gzip
    from norway_company_agent.sampling import iter_bulk
    text = '"organisasjonsnummer";"navn";"organisasjonsform.kode"\n"123456785";"FOO AS";"AS"\n'
    plain = tmp_path / "plain.csv"
    plain.write_text(text, encoding="utf-8")
    packed = tmp_path / "packed.csv"
    with gzip.open(packed, "wt", encoding="utf-8") as handle:
        handle.write(text)
    assert [r["organisation_number"] for r in iter_bulk(plain)] == [r["organisation_number"] for r in iter_bulk(packed)] == ["123456785"]


def test_robots_rfc9309(monkeypatch):
    import urllib.error
    from norway_company_agent import website as W

    def raiser(exc):
        def open_(request, timeout=None):
            raise exc
        return open_

    W._ROBOTS_CACHE.clear()
    monkeypatch.setattr(W, "assert_public_url", lambda url: None)
    monkeypatch.setattr(W.SAFE_OPENER, "open", raiser(urllib.error.HTTPError("https://a.no/robots.txt", 404, "nf", {}, None)))
    assert W._robots_allowed("https://a.no/x", 5) is True
    monkeypatch.setattr(W.SAFE_OPENER, "open", raiser(urllib.error.HTTPError("https://b.no/robots.txt", 503, "down", {}, None)))
    assert W._robots_allowed("https://b.no/x", 5) is False
    monkeypatch.setattr(W.SAFE_OPENER, "open", raiser(urllib.error.URLError("timed out")))
    assert W._robots_allowed("https://c.no/x", 5) is False and W.robots_unreachable("https://c.no/y")
    monkeypatch.setattr(W.SAFE_OPENER, "open", raiser(OSError("run request budget exhausted (1950)")))
    assert W._robots_allowed("https://d.no/x", 5) is False and "https://d.no/robots.txt" not in W._ROBOTS_CACHE
    W._ROBOTS_CACHE.clear()


def test_output_keeps_no_page_text_and_nothing_from_unverified_sites():
    from norway_company_agent.footprint.redact import redact_for_output
    page = {"url": "https://therma.no/kontakt", "title": "Kontakt", "main_text_excerpt": "Ola Nordmann mobil 912 34 567 ola@therma.no",
            "identity_text_excerpt": "ola@therma.no", "dated_activity": [{"title": "x"}]}
    unverified = {"status": "available", "value": {"final_url": "https://therma.no/", "title": "Therma", "description": "Kulde",
                  "main_text_excerpt": "Ola Nordmann", "identity_text_excerpt": "912 34 567", "social_links": [{"url": "https://facebook.com/therma"}],
                  "pages": [page], "identity_assessment": {"publishable": False}}}
    profile = redact_for_output({"evidence": {"website": unverified}})
    dumped = str(profile)
    assert "Ola" not in dumped and "912 34 567" not in dumped and "facebook" not in dumped and "Kulde" not in dumped
    assert profile["evidence"]["website"]["value"]["title"] == "Therma"
    verified = {"status": "available", "value": {"final_url": "https://foo.no/", "description": "Foo leverer rør", "main_text_excerpt": "Kari 99999999",
                "social_links": [{"url": "https://facebook.com/foo"}], "pages": [], "identity_assessment": {"publishable": True}}}
    kept = redact_for_output({"evidence": {"website": verified}})["evidence"]["website"]["value"]
    assert "main_text_excerpt" not in kept and kept["description"] == "Foo leverer rør" and kept["social_links"]


def test_group_handles_are_not_the_entity():
    from norway_company_agent.identity import assess_social_identity
    profile = {"name": "FJØSSYSTEMER AS"}
    assert not assess_social_identity(profile, {"platform": "facebook", "url": "https://facebook.com/fjossystemergruppen"})["publishable"]
    assert assess_social_identity(profile, {"platform": "facebook", "url": "https://facebook.com/fjossystemer"})["publishable"]


def test_group_member_needs_a_proof_for_activity():
    item = {"title": "Nytt lager", "date": "2026-03-01", "url": "https://fjossystemer.no/nytt-lager", "method": "json-ld"}
    site = _site("https://fjossystemer.no/", dated_activity=[item])
    profile = {"name": "FJØSSYSTEMER AS", "evidence": {"website": site, "registry_live": {"status": "available", "value": {"in_group": True}}}}
    acts = [c for c in flatten_external_claims(profile) if c["field"] == "dated_activity"]
    assert acts[0]["availability"] == "not_available"


def test_unread_feed_is_blocked_not_absent():
    site = _site("https://foo.no/", feed_link="https://foo.no/feed/", feed_activity={"items": [], "skipped": "request budget or run deadline (policy)"})
    acts = [c for c in flatten_external_claims({"name": "FOO AS", "evidence": {"website": site}}) if c["field"] == "dated_activity"]
    assert acts[0]["availability"] == "blocked"


def test_truncated_nav_feed_fails_instead_of_reporting_no_vacancy():
    from norway_company_agent.footprint import io as fio
    out, _ = fio.nav_jobs_for_batch({"1": {"name": "FOO AS"}}, prefetched=({}, {"requests": 3, "truncated": "page cap 3 reached"}))
    assert out["1"]["status"] == "source_error" and "incomplete" in out["1"]["note"]


def test_contact_proof_keeps_a_text_span_for_companies_only():
    from norway_company_agent.footprint.domain import identity_proof
    base = {"organisation_number": "810034882", "name": "SANDNES ELEKTRISKE AS", "registry": {"phone": "+47 51 66 00 00"}}
    unique = {"phone": {"51660000": 1}, "address": {}}
    page = ["Sandnes Elektriske AS · Telefon 51 66 00 00"]
    company = identity_proof({**base, "legal_form": "AS"}, page, collisions=unique)
    assert company["proof"] == "contact" and "51 66 00 00" in company["snippet"]
    sole = identity_proof({**base, "legal_form": "ENK"}, page, collisions=unique)
    assert "51 66" not in sole["snippet"] and "sha256" in sole["snippet"]

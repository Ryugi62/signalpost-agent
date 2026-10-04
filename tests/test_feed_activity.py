"""AC-22..AC-24: dated activity from the verified site's own RSS/Atom feed, and registry reads reserved first."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.footprint.domain import feed_link, flatten_external_claims, parse_feed_items  # noqa: E402

NOW = "2026-10-04T12:00:00Z"

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Foo AS » Feed</title>
<item><title>Ny avtale med Sandnes kommune</title><link>https://www.foo.no/nyheter/avtale/</link><pubDate>Wed, 30 Sep 2026 12:48:36 +0000</pubDate></item>
<item><title>Hei, verden!</title><link>https://foo.no/hei-verden/</link><pubDate>Fri, 25 Sep 2026 11:10:42 +0000</pubDate></item>
<item><title>Hello world!</title><link>https://foo.no/hello-world/</link><pubDate>Fri, 25 Sep 2026 11:10:42 +0000</pubDate></item>
<item><title>Lorem ipsum dolor sit amet</title><link>https://foo.no/lorem/</link><pubDate>Fri, 25 Sep 2026 11:10:42 +0000</pubDate></item>
<item><title>Keep in Touch with Site Visitors and Boost Loyalty</title><link>https://foo.no/post/k</link><pubDate>Sun, 01 Jun 2025 10:00:00 +0000</pubDate></item>
<item><title>Tips for Writing Great Posts that Increase Your Site Traffic</title><link>https://foo.no/post/t</link><pubDate>Sun, 01 Jun 2025 10:00:00 +0000</pubDate></item>
<item><title>Gammel nyhet</title><link>https://foo.no/gammel/</link><pubDate>Mon, 26 Feb 2018 06:42:57 +0000</pubDate></item>
<item><title>Fremtidig</title><link>https://foo.no/fremtid/</link><pubDate>Mon, 26 Feb 2029 06:42:57 +0000</pubDate></item>
<item><title>Annen side</title><link>https://other.no/post/</link><pubDate>Tue, 01 Sep 2026 10:00:00 +0000</pubDate></item>
<item><title>Om oss</title><link>https://foo.no/om-oss/</link><pubDate>Tue, 01 Sep 2026 10:00:00 +0000</pubDate></item>
<item><title>Ny avtale med Sandnes kommune</title><link>https://foo.no/dup/</link><pubDate>Tue, 29 Sep 2026 10:00:00 +0000</pubDate></item>
<item><title>Uten dato</title><link>https://foo.no/x/</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Bar</title>
<entry><title>Bar åpner i Bergen</title><link href="https://bar.no/blog/bergen"/><published>2026-08-14T13:00:13Z</published></entry>
<entry><title>Oppdatert</title><link rel="alternate" href="/blog/oppdatert"/><updated>2026-07-07T10:16:27+02:00</updated></entry>
</feed>"""


def test_ac22_rss_items_filtered():
    items = parse_feed_items(RSS, feed_url="https://foo.no/feed/", site_domain="foo.no", now=NOW)
    assert [(i["title"], i["date"]) for i in items] == [("Ny avtale med Sandnes kommune", "2026-09-30")]
    assert items[0]["url"] == "https://www.foo.no/nyheter/avtale/"
    assert items[0]["method"] == "rss" and items[0]["type"] == "feed_post"


def test_ac22_atom_items_and_relative_links():
    items = parse_feed_items(ATOM, feed_url="https://bar.no/feed.xml", site_domain="bar.no", now=NOW)
    assert [(i["date"], i["url"]) for i in items] == [("2026-08-14", "https://bar.no/blog/bergen"), ("2026-07-07", "https://bar.no/blog/oppdatert")]


def test_ac22_bad_xml_is_empty():
    assert parse_feed_items("<html>not a feed", feed_url="https://foo.no/feed/", site_domain="foo.no", now=NOW) == []


def test_ac23_feed_link_choice():
    html = """<head>
    <link rel="alternate" type="application/json+oembed" href="https://foo.no/wp-json/oembed/1.0/embed?url=x">
    <link rel="alternate" type="text/xml+oembed" href="https://foo.no/wp-json/oembed/1.0/embed?url=x&format=xml">
    <link rel="alternate" type="application/rss+xml" title="Foo » Kommentarer" href="https://foo.no/comments/feed/">
    <link rel="alternate" type="application/rss+xml" title="Foo » Feed" href="/feed/">
    </head>"""
    assert feed_link(html, "https://www.foo.no/") == "https://www.foo.no/feed/"
    assert feed_link('<link rel="alternate" type="application/rss+xml" href="https://feeds.example.com/foo">', "https://foo.no/") is None
    assert feed_link('<link rel="alternate" type="application/atom+xml" href="https://blog.foo.no/atom.xml">', "https://foo.no/") == "https://blog.foo.no/atom.xml"
    assert feed_link("<p>no feed</p>", "https://foo.no/") is None


def _site(**extra):
    value = {"final_url": "https://foo.no/", "identity_assessment": {"publishable": True, "reasons": ["x"]}, "social_links": [], "pages": []}
    value.update(extra)
    return {"status": "available", "source_url": "https://foo.no/", "retrieved_at": "t", "value": value}


def test_ac22_feed_items_become_dated_activity_claims():
    feed = {"feed_url": "https://foo.no/feed/", "retrieved_at": "t2", "content_sha256": "abc",
            "items": parse_feed_items(RSS, feed_url="https://foo.no/feed/", site_domain="foo.no", now=NOW)}
    claims = flatten_external_claims({"evidence": {"website": _site(feed_activity=feed)}})
    acts = [c for c in claims if c["field"] == "dated_activity" and c["availability"] == "available"]
    assert len(acts) == 1
    assert acts[0]["source_url"] == "https://foo.no/feed/" and acts[0]["method"] == "company_site_rss"
    assert acts[0]["retrieved_at"] == "t2" and acts[0]["effective_at"] == "2026-09-30"


def test_ac23_feed_read_only_for_published_site_with_link(monkeypatch):
    from norway_company_agent.footprint import io as fio
    calls = []

    def fake_get(url, max_bytes=1_000_000, timeout=10.0):
        calls.append(url)
        return RSS.encode(), "https://foo.no/feed/"

    monkeypatch.setattr(fio, "_get_feed", fake_get)
    monkeypatch.setattr(fio, "_robots_allowed", lambda url, timeout: True)
    unpublished = {"status": "available", "value": {"final_url": "https://foo.no/", "feed_link": "https://foo.no/feed/", "identity_assessment": {"publishable": False}}}
    assert fio.attach_feed_activity(unpublished, now=NOW) == 0 and calls == []
    no_link = _site()
    assert fio.attach_feed_activity(no_link, now=NOW) == 0 and calls == []
    site = _site(feed_link="https://foo.no/feed/", registered_domain="foo.no")
    assert fio.attach_feed_activity(site, now=NOW) == 1 and calls == ["https://foo.no/feed/"]
    assert site["value"]["feed_activity"]["items"][0]["date"] == "2026-09-30"


def test_ac23_feed_failure_is_recorded_not_raised(monkeypatch):
    from norway_company_agent.footprint import io as fio

    def boom(url, max_bytes=1_000_000, timeout=10.0):
        raise OSError("run request budget exhausted")

    monkeypatch.setattr(fio, "_get_feed", boom)
    monkeypatch.setattr(fio, "_robots_allowed", lambda url, timeout: True)
    site = _site(feed_link="https://foo.no/feed/", registered_domain="foo.no")
    fio.attach_feed_activity(site, now=NOW)
    assert site["value"]["feed_activity"]["items"] == [] and "budget" in site["value"]["feed_activity"]["error"]


def test_ac24_registry_reads_reserved_before_discovery():
    from norway_company_agent.budget import plan_shares, registry_reserve
    assert registry_reserve(1000, group_candidates=43) == 1000 + 20 + 43
    for n in (100, 1000, 1100):
        plan = plan_shares(1950, n, registry_sites=110, group_candidates=int(n * 0.05), financials_floor=registry_reserve(n, group_candidates=int(n * 0.05)))
        assert plan["ceilings"]["financials"] >= n
        assert sum(plan["ceilings"].values()) <= 1950


def test_ac25_jsonld_same_as_profiles_join_the_social_candidates():
    from norway_company_agent.website import merge_social_links, structured_social_links
    anchors = [{"platform": "facebook", "url": "https://facebook.com/foo"}]
    orgs = [{"@type": "Organization", "name": "Foo AS", "sameAs": ["https://www.facebook.com/foo", "https://www.instagram.com/foo_as/", "https://foo.no/"]}]
    merged = merge_social_links(anchors, structured_social_links(orgs))
    assert merged == [{"platform": "facebook", "url": "https://facebook.com/foo"}, {"platform": "instagram", "url": "https://instagram.com/foo_as"}]


def test_ac23_group_site_without_org_number_gets_no_feed_read(monkeypatch):
    from norway_company_agent.footprint import io as fio
    calls = []
    monkeypatch.setattr(fio, "_get_feed", lambda url, max_bytes=1_000_000, timeout=10.0: calls.append(url) or (RSS.encode(), url))
    monkeypatch.setattr(fio, "_robots_allowed", lambda url, timeout: True)
    group = _site(feed_link="https://plasman.com/feed/", registered_domain="plasman.com", final_url="https://plasman.com/")
    group["value"]["identity_assessment"]["method"] = "deterministic_name_org_evidence_v2"
    assert fio.attach_feed_activity(group, now=NOW) == 0 and calls == []
    proven = _site(feed_link="https://foo.com/feed/", registered_domain="foo.com", final_url="https://foo.com/")
    proven["value"]["identity_assessment"]["method"] = "deterministic_domain_discovery_org_proof_v1"
    assert fio.attach_feed_activity(proven, now=NOW) == 1

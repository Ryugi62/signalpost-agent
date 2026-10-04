"""Output privacy (pure): page text read for identity checks never leaves the run.

Company pages carry staff names, mobile numbers and personal e-mails. They are read to prove identity and to pick out
role mailboxes, then dropped: the published profile keeps URLs, titles, hashes, proof snippets (e-mails masked) and the
claims. A site that failed the identity gate keeps no description, links or dated items either (they may belong to
another company)."""
from __future__ import annotations

from typing import Any

TEXT_KEYS = ("main_text_excerpt", "identity_text_excerpt")
UNVERIFIED_KEYS = ("description", "social_links", "discovered_social_links", "social_link_assessments", "dated_activity",
                   "structured_organisations", "feed_link", "feed_activity")


def _clean(record: Any, *, verified: bool) -> None:
    if not isinstance(record, dict) or not isinstance(record.get("value"), dict):
        return
    value = record["value"]
    for key in TEXT_KEYS:
        value.pop(key, None)
    if not verified:
        for key in UNVERIFIED_KEYS:
            value.pop(key, None)
    for page in value.get("pages") or []:
        if isinstance(page, dict):
            for key in TEXT_KEYS:
                page.pop(key, None)
            if not verified:
                page.pop("dated_activity", None)
    value["text_withheld"] = "Page text was read for identity checks only and is not published (personal data)."


def redact_for_output(profile: dict[str, Any]) -> dict[str, Any]:
    evidence = profile.get("evidence") or {}
    site = evidence.get("website") or {}
    verified = bool(((site.get("value") or {}) if isinstance(site.get("value"), dict) else {}).get("identity_assessment", {}).get("publishable")) \
        and site.get("status") == "available"
    _clean(site, verified=verified)
    _clean(evidence.get("website_registry_unverified"), verified=False)
    return profile

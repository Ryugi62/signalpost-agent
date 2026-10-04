"""Material changes since the previous run of the same command (pure; no I/O).

Built on the starter's `diff_profile`. A field is compared only when both runs actually read it (status available or
not_found on both sides): a value missing because a source was blocked or failed in one run is listed under
`not_compared`, never reported as a change (false changes are scored)."""
from __future__ import annotations

from typing import Any

from ..refresh import _evidence_for, diff_profile

READ_STATES = {"available", "not_found", "not_applicable"}


def _claim(profile: dict[str, Any], field: str) -> dict[str, Any]:
    return next((c for c in profile.get("external_claims") or [] if c.get("field") == field), {})


def material_changes(previous: dict[str, Any] | None, current: dict[str, Any], *, previous_run_id: str | None = None) -> dict[str, Any]:
    if not previous:
        return {"compared": False, "note": "No earlier profile for this organisation number at this output location; nothing to compare."}
    changes: list[dict[str, Any]] = []
    not_compared: list[str] = []
    for change in diff_profile(previous, current):
        field = change["field"]
        if not field.startswith("registry."):
            old_state = _evidence_for(previous, field).get("status")
            new_state = _evidence_for(current, field).get("status")
            if old_state not in READ_STATES or new_state not in READ_STATES:
                not_compared.append(field)
                continue
        changes.append(change)
    old_site, new_site = _claim(previous, "official_website"), _claim(current, "official_website")
    if {old_site.get("availability"), new_site.get("availability")} <= {"available", "not_available"} and old_site.get("value") != new_site.get("value"):
        changes.append({"organisation_number": current.get("organisation_number"), "field": "external.official_website",
                        "old_value": old_site.get("value"), "new_value": new_site.get("value"),
                        "source_url": new_site.get("source_url") or old_site.get("source_url"), "retrieved_at": new_site.get("retrieved_at")})
    elif old_site.get("value") != new_site.get("value"):
        not_compared.append("external.official_website")
    old_jobs = {(c.get("source_url")) for c in previous.get("external_claims") or [] if c.get("field") == "job_postings" and c.get("availability") == "available"}
    new_jobs = {(c.get("source_url")) for c in current.get("external_claims") or [] if c.get("field") == "job_postings" and c.get("availability") == "available"}
    if old_jobs != new_jobs and {_claim(previous, "job_postings").get("availability"), _claim(current, "job_postings").get("availability")} <= {"available", "not_available"}:
        changes.append({"organisation_number": current.get("organisation_number"), "field": "external.job_postings",
                        "old_value": sorted(u for u in old_jobs if u), "new_value": sorted(u for u in new_jobs if u),
                        "source_url": "https://pam-stilling-feed.nav.no/api/v1/feed", "retrieved_at": _claim(current, "job_postings").get("retrieved_at")})
    return {"compared": True, "previous_run_id": previous_run_id, "previous_retrieved_at": (previous.get("evidence", {}).get("registry") or {}).get("retrieved_at"),
            "changes": changes, "not_compared": sorted(set(not_compared))}

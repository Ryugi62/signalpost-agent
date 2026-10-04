#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import profile_complete_for_modules, profiles_from_bulk, read_organisation_inputs, terminal_envelope, validate_envelopes  # noqa: E402
from norway_company_agent.evidence import utc_now  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402
from norway_company_agent.footprint.brief import company_brief  # noqa: E402
from norway_company_agent.footprint.domain import flatten_external_claims  # noqa: E402
from norway_company_agent.footprint.io import attach_feed_activity, discover_website, nav_jobs_for_batch, registry_collisions, wikidata_for_batch  # noqa: E402
from norway_company_agent.footprint.domain import FREE_MAIL  # noqa: E402
from norway_company_agent.footprint.refresh_v2 import material_changes  # noqa: E402
from norway_company_agent.budget import DEFAULT_LIMIT, REGISTRY_CATEGORIES, RequestBudget, plan_shares, registry_reserve  # noqa: E402
from norway_company_agent.http_gate import charging, install_request_gate  # noqa: E402
from norway_company_agent.http import fetch_json  # noqa: E402
from norway_company_agent.official import BRREG_GROUP  # noqa: E402
from norway_company_agent.registry_batch import fetch_live_entities, fetch_roles_bulk, fetch_subunits_bulk  # noqa: E402

BUDGET_NOTE = "Not requested: the run's outbound request budget (policy) was spent on higher-priority sources"


def mark_budget_refusals(profile: dict) -> None:
    """A record refused by the request gate is a policy block, not a source failure."""
    for key, record in (profile.get("evidence") or {}).items():
        if isinstance(record, dict) and record.get("status") == "source_error" and "budget" in str(record.get("note") or "").casefold():
            record["status"] = "blocked"
            record["note"] = BUDGET_NOTE


def budget_blocked(field: str, source_type: str, url: str) -> dict:
    from norway_company_agent.evidence import evidence as _ev
    return _ev(field, "blocked", source_type, url, note=BUDGET_NOTE)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            # U+2028/U+2029 are valid inside JSON strings but break line-based readers; escape them.
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":")).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
            handle.write(line + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluator-owned Signalpost batch contract")
    parser.add_argument("--organisations", required=True, help="JSON, JSONL, or text organisation-number list")
    parser.add_argument("--bulk", required=True, help="Frozen Brreg entity snapshot")
    parser.add_argument("--output", required=True, help="Terminal envelope JSONL")
    parser.add_argument("--profiles-output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-count", type=int, default=100)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--checkpoint-every", type=int, default=25, help="Accepted for starter compatibility; unused (a v2 run is phase-based and completes in one pass)")
    parser.add_argument("--resume", action="store_true", help="Accepted for starter compatibility; unused (see --previous for refresh)")
    parser.add_argument("--previous", default=None,
                        help="Profiles JSONL of the previous run to compare against (default: the existing --profiles-output file, which is archived before it is replaced)")
    parser.add_argument("--modules", default="registry,accounting_obligation,registry_live,financials,roles,group,locations,website,website_discovery,jobs,wikidata")
    parser.add_argument("--deadline-minutes", type=float, default=38.0, help="After this, remaining companies skip website crawling/discovery (envelopes still emitted)")
    parser.add_argument("--max-discovery-requests", type=int, default=1650, help="Hard cap on HTTP requests spent on domain discovery per run")
    parser.add_argument("--nav-days", type=int, default=45, help="NAV vacancy-feed window in days (45 days hold 97%% of active ads, measured 2026-10-04)")
    parser.add_argument("--max-outbound-requests", type=int, default=DEFAULT_LIMIT,
                        help="Hard ceiling on every outbound HTTP request of the run (registry, sites, NAV, Wikidata, robots.txt, retries, redirects)")
    parser.add_argument("--registry-secondary-pages", type=int, default=2, help="Secondary pages read on a registry-declared website")
    parser.add_argument("--budget-scope", choices=["all", "external"], default="all",
                        help="all (default): the ceiling covers every request, registry included. external: registry reads are counted but not capped")
    parser.add_argument("--financials-floor", type=int, default=-1,
                        help="Requests kept back from discovery for annual accounts and group structure (-1 = one per company + 2%% + group candidates)")
    args = parser.parse_args()

    started_at = utc_now()
    budget = RequestBudget(args.max_outbound_requests, exempt=REGISTRY_CATEGORIES if args.budget_scope == "external" else frozenset())
    uninstall_gate = install_request_gate(budget)  # every HTTP request below is counted and capped here
    organisation_inputs = read_organisation_inputs(args.organisations)
    orgs = [item["organisation_number"] for item in organisation_inputs]
    if len(orgs) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} organisations, received {len(orgs)}")
    profiles, registry_metadata = profiles_from_bulk(args.bulk, orgs)
    by_org = {profile["organisation_number"]: profile for profile in profiles}
    annotations = {item["organisation_number"]: item for item in organisation_inputs}
    for profile in profiles:
        for key in ("evaluation_split", "sample_slice"):
            if key in annotations[profile["organisation_number"]]:
                profile[key] = annotations[profile["organisation_number"]][key]
    requested_modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    operations = {"dns_lookups": 0, "latencies_ms": []}

    import threading
    import time as _time
    run_t0 = _time.monotonic()

    def over_deadline() -> bool:
        return (_time.monotonic() - run_t0) / 60.0 > args.deadline_minutes

    # Budget plan, part 1: the batch reads are cheap and fixed; set their ceilings before any request.
    nav_pages = int(args.nav_days * 2.2) + 10  # the feed carries ~1.9 pages per day (all states)
    strict = args.budget_scope == "all"
    pre_floor = (registry_reserve(len(orgs)) if args.financials_floor < 0 else args.financials_floor) if strict else 0
    pre_plan = plan_shares(budget.limit, len(orgs), registry_sites=sum(1 for p in profiles if p.get("website")), financials_floor=pre_floor, nav_pages=nav_pages)
    for category in ("registry_batch", "registry_bulk", "wikidata", "jobs"):
        budget.set_ceiling(category, pre_plan["ceilings"][category])
    batch_reports: dict = {}
    wanted = set(orgs)

    def charged(category, fn, *a, **kw):
        with charging(category):
            return fn(*a, **kw)

    background = ThreadPoolExecutor(max_workers=3)
    subunit_future = background.submit(charged, "registry_bulk", fetch_subunits_bulk, wanted) if "locations" in requested_modules else None
    roles_future = background.submit(charged, "registry_bulk", fetch_roles_bulk, wanted) if "roles" in requested_modules else None
    nav_future = None
    if "jobs" in requested_modules:
        from norway_company_agent.footprint.io import nav_active_entries
        nav_future = background.submit(charged, "jobs", nav_active_entries, args.nav_days, max_pages=pre_plan["ceilings"]["jobs"] - 12)

    collisions = registry_collisions(args.bulk) if "website_discovery" in requested_modules else None
    if "registry_live" in requested_modules:
        with charging("registry_batch"):
            live, live_metrics = fetch_live_entities(orgs)
        for org, record in live.items():
            by_org[org]["evidence"]["registry_live"] = record
        batch_reports["registry_live"] = live_metrics
    wikidata = {}
    if "wikidata" in requested_modules:
        with charging("wikidata"):
            wikidata, wikidata_metrics = wikidata_for_batch(orgs)
        for org in orgs:
            by_org[org]["evidence"]["wikidata"] = wikidata[org]
        batch_reports["wikidata"] = wikidata_metrics

    def in_group(profile: dict) -> bool:
        return bool((((profile["evidence"].get("registry_live") or {}).get("value") or {}).get("in_group")))

    # Budget plan, part 2: now that the group flags are known, cap the per-company categories.
    group_candidates = sum(1 for p in profiles if in_group(p))
    floor = (registry_reserve(len(orgs), group_candidates=group_candidates) if args.financials_floor < 0 else args.financials_floor) if strict else 0
    plan = plan_shares(budget.limit, len(orgs), registry_sites=sum(1 for p in profiles if p.get("website")),
                       group_candidates=group_candidates, financials_floor=floor, nav_pages=nav_pages)
    if strict:  # AC-24: annual accounts and group structure are kept back before any website work
        budget.reserve("financials", floor - group_candidates)
        budget.reserve("group", group_candidates)
    budget.set_ceiling("website_registry", plan["ceilings"]["website_registry"])
    budget.set_ceiling("activity_feed", plan["ceilings"]["activity_feed"])

    def read_feed(site: dict, name=None) -> None:
        """AC-23: one feed read for a site that passed the identity gate and declares its own posts feed."""
        value = site.get("value") if isinstance(site.get("value"), dict) else {}
        if value.get("feed_link") and not over_deadline() and budget.available("activity_feed") > 0:
            with charging("activity_feed"):
                attach_feed_activity(site, name=name)
    budget.set_ceiling("website_discovery", 0)  # opened after the registry-website phase with whatever is left
    budget.set_ceiling("financials", plan["wanted"]["financials"])
    budget.set_ceiling("group", plan["wanted"]["group"])

    def registry_phase(profile: dict) -> dict:
        org = profile["organisation_number"]
        latencies = []
        if "website" in requested_modules:
            from norway_company_agent.evidence import evidence as _ev
            if over_deadline():
                profile["evidence"]["website"] = _ev("website", "blocked", "registry_linked_company_website", profile.get("website") or "about:blank", note="Not requested: run deadline (policy)")
            elif profile.get("website") and budget.available("website_registry") < 2:
                profile["evidence"]["website"] = budget_blocked("website", "registry_linked_company_website", profile.get("website"))
            else:
                with charging("website_registry"):
                    website_record, website_metrics = fetch_website(profile.get("website"), max_secondary=args.registry_secondary_pages)
                profile["evidence"]["website"] = apply_website_identity_gate(profile, website_record)["website"]
                latencies += website_metrics["latencies_ms"]
                read_feed(profile["evidence"]["website"], profile.get("name"))
        return {"latencies_ms": latencies}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for metric in pool.map(registry_phase, profiles):
            operations["latencies_ms"].extend(metric["latencies_ms"])

    # Workplaces are needed before discovery (subunit websites, e-mail domains and names are candidates).
    if subunit_future is not None:
        locations, subunit_metrics = subunit_future.result()
        for org, record in locations.items():
            by_org[org]["evidence"]["locations"] = record
        batch_reports["locations"] = subunit_metrics

    # Discovery gets everything the earlier phases did not use, minus what the NAV feed may still need.
    jobs_left = max(0, budget.snapshot()["ceilings"].get("jobs", 0) - budget.snapshot()["by_category"].get("jobs", 0)) if nav_future is not None else 0
    budget.reserve("jobs", jobs_left)
    budget.set_ceiling("website_discovery", None)
    discovery_start = budget.snapshot()

    def site_published(profile: dict) -> bool:
        site = profile["evidence"].get("website") or {}
        return site.get("status") == "available" and bool(((site.get("value") or {}).get("identity_assessment") or {}).get("publishable"))

    def extra_hosts(profile: dict) -> list:
        hosts = []
        locs = ((profile["evidence"].get("locations") or {}).get("value") or {}).get("locations") or []
        for loc in locs:
            domain = loc.get("email_domain")
            if domain and domain not in FREE_MAIL and domain not in hosts:
                hosts.append(domain)
        for claim in (((profile["evidence"].get("wikidata") or {}).get("value") or {}).get("claims") or []):
            if claim.get("field") == "official_website" and claim.get("value"):
                hosts.append(claim["value"])
        return hosts[:3]

    def discovery_phase(profile: dict) -> dict:
        from norway_company_agent.evidence import evidence as _ev
        site = profile["evidence"].get("website") or {}
        if site_published(profile):
            profile["evidence"]["website_discovery"] = {**site, "field": "website_discovery", "status": "not_applicable", "value": None,
                                                        "note": "Registry-linked website already passed the identity gate"}
            return {"latencies_ms": [], "dns_lookups": 0}
        if over_deadline() or budget.available("website_discovery") < 2 and not (site.get("status") == "available"):
            profile["evidence"]["website_discovery"] = _ev("website_discovery", "blocked",
                                                           "deterministic_domain_discovery", "about:blank",
                                                           note=BUDGET_NOTE if not over_deadline() else "Not requested: run deadline (policy)")
            return {"latencies_ms": [], "dns_lookups": 0}
        try:
            with charging("website_discovery"):
                found, discovery, metrics = discover_website(
                    profile, collisions=collisions, prior_record=site if site.get("status") == "available" else None,
                    extra_hosts=extra_hosts(profile), can_spend=lambda: budget.available("website_discovery") >= 2)
        except Exception as exc:  # never drop the envelope
            found, discovery, metrics = None, _ev("website_discovery", "source_error", "deterministic_domain_discovery", "about:blank",
                                                  note=f"{type(exc).__name__}: {str(exc)[:160]}"), {"latencies_ms": [], "dns_lookups": 0}
        profile["evidence"]["website_discovery"] = discovery
        if found:
            if site.get("status") == "available" and found.get("source_class") != "registry_linked_company_website":
                profile["evidence"]["website_registry_unverified"] = site
            profile["evidence"]["website"] = found
            read_feed(found, profile.get("name"))
        return metrics

    # Discovery in two passes around the per-company registry reads (marginal value per request, measured on a
    # 1,000-company batch): companies with a registry website, a registry e-mail domain of their own or staff yield one
    # site per ~25-30 requests; the rest (~70% of companies) one per ~85, less than one annual account per request.
    def _priority(profile: dict) -> tuple:
        raw = ((profile.get("evidence") or {}).get("registry") or {}).get("value") or {}
        site = profile["evidence"].get("website") or {}
        email = str(raw.get("epostadresse") or "").casefold()
        own_mail = "@" in email and email.rsplit("@", 1)[1] not in FREE_MAIL
        return (0 if site.get("status") == "available" else 1, 0 if own_mail else 1, 0 if profile.get("employees") else 1)
    ranked = sorted(profiles, key=_priority)
    high_yield = [p for p in ranked if _priority(p) != (1, 1, 1)]
    low_yield = [p for p in ranked if _priority(p) == (1, 1, 1)]

    def run_discovery(batch: list) -> None:
        if "website_discovery" not in requested_modules or not batch:
            return
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for metric in pool.map(discovery_phase, batch):
                operations["latencies_ms"].extend(metric.get("latencies_ms") or [])
                operations["dns_lookups"] += metric.get("dns_lookups", 0)

    run_discovery(high_yield)
    discovery_end = budget.snapshot()

    def per_company_registry(profile: dict) -> dict:
        org = profile["organisation_number"]
        latencies = []
        if "financials" in requested_modules:
            if budget.available("financials") > 0:
                with charging("financials"):
                    records, metrics = fetch_official_modules(org, {"financials"}, fetcher=lambda url: fetch_json(url, attempts=2))
                profile["evidence"].update(records)
                latencies += [m.elapsed_ms for m in metrics]
            else:
                profile["evidence"]["financials"] = budget_blocked("financials", "official_annual_accounts", f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}")
        if "group" in requested_modules:
            if not in_group(profile):
                from norway_company_agent.evidence import evidence as _ev
                profile["evidence"]["group"] = _ev("group", "not_applicable", "official_group_structure", BRREG_GROUP.format(org=org),
                                                   note="The registry row does not mark this entity as part of a group (erIKonsern = false)")
            elif budget.available("group") > 0:
                with charging("group"):
                    records, metrics = fetch_official_modules(org, {"group"}, fetcher=lambda url: fetch_json(url, attempts=2))
                profile["evidence"].update(records)
            else:
                profile["evidence"]["group"] = budget_blocked("group", "official_group_structure", BRREG_GROUP.format(org=org))
        return {"latencies_ms": latencies}

    budget.release("financials")
    budget.release("group")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for metric in pool.map(per_company_registry, profiles):
            operations["latencies_ms"].extend(metric["latencies_ms"])
    run_discovery(low_yield)  # whatever the registry reads left
    low_pass_end = budget.snapshot()

    if roles_future is not None:
        roles, roles_metrics = roles_future.result()
        for org, record in roles.items():
            by_org[org]["evidence"]["roles"] = record
        batch_reports["roles"] = roles_metrics
    ordered_profiles = [by_org[org] for org in orgs]
    resumed_profiles = 0
    profiles_output = Path(args.profiles_output)
    if "jobs" in requested_modules:
        job_orgs = {}
        for profile in ordered_profiles:
            locations = ((profile["evidence"].get("locations") or {}).get("value") or {}).get("locations") or []
            job_orgs[profile["organisation_number"]] = {
                "name": profile.get("name"),
                "subunits": [item.get("organisation_number") for item in locations if item.get("organisation_number")],
                "subunit_names": [item.get("name") for item in locations if item.get("name")],
            }
        with charging("jobs"):
            jobs, jobs_metrics = nav_jobs_for_batch(job_orgs, days=args.nav_days, prefetched=nav_future, max_details=10)
        for profile in ordered_profiles:
            profile["evidence"]["jobs"] = jobs[profile["organisation_number"]]
        batch_reports["jobs"] = jobs_metrics
    background.shutdown(wait=True)
    uninstall_gate()
    for profile in ordered_profiles:
        mark_budget_refusals(profile)
    # Refresh: compare with the previous run of the same command and preserve that snapshot (never overwritten in place).
    previous_path = Path(args.previous) if args.previous else (profiles_output if profiles_output.exists() else None)
    previous_by_org: dict = {}
    if previous_path is not None and previous_path.exists():
        for line in previous_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                previous_by_org[row.get("organisation_number")] = row
        if previous_path == profiles_output:
            prior_run = next((row.get("run_id") for row in previous_by_org.values() if row.get("run_id")), None) or "previous"
            archive = profiles_output.with_name(f"{profiles_output.stem}.before-{prior_run}{profiles_output.suffix}")
            archive.write_bytes(profiles_output.read_bytes())
    for profile in ordered_profiles:
        try:
            profile["external_claims"] = flatten_external_claims(profile)
        except Exception as exc:  # never lose the batch over one profile
            profile["external_claims"] = [{"field": "official_website", "value": None, "availability": "failed", "note": f"{type(exc).__name__}: {str(exc)[:120]}"},
                                          {"field": "job_postings", "value": None, "availability": "failed"}]
        profile["run_id"] = args.run_id
        prior = previous_by_org.get(profile["organisation_number"])
        try:
            profile["refresh"] = material_changes(prior, profile, previous_run_id=(prior or {}).get("run_id"))
        except Exception as exc:
            profile["refresh"] = {"compared": False, "note": f"comparison failed: {type(exc).__name__}"}
        try:
            profile["company_brief"] = company_brief(profile)
        except Exception as exc:
            profile["company_brief"] = {"sentences": [], "unknowns": [{"topic": "brief", "note": f"failed: {type(exc).__name__}"}], "llm": False}
    completed_at = utc_now()
    envelopes = [
        terminal_envelope(profile, run_id=args.run_id, modules=requested_modules, started_at=started_at, completed_at=completed_at)
        for profile in ordered_profiles
    ]
    validation = validate_envelopes(envelopes, args.expected_count)
    write_jsonl(profiles_output, ordered_profiles)
    write_jsonl(Path(args.output), envelopes)
    budget_snapshot = budget.snapshot()
    operations["requests"] = budget_snapshot["spent"]  # exact: counted by the request gate, every module included
    operations["by_module"] = budget_snapshot["by_category"]
    latencies = sorted(operations.pop("latencies_ms"))
    operations["p50_ms"] = latencies[len(latencies) // 2] if latencies else None
    operations["p95_ms"] = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    report = {
        "run_id": args.run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "expected_count": args.expected_count,
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed_profiles,
        "refresh": {"previous": str(previous_path) if previous_by_org else None,
                    "compared_profiles": sum(1 for p in ordered_profiles if (p.get("refresh") or {}).get("compared")),
                    "profiles_with_changes": sum(1 for p in ordered_profiles if (p.get("refresh") or {}).get("changes")),
                    "changes": sum(len((p.get("refresh") or {}).get("changes") or []) for p in ordered_profiles)},
        "profiles_fetched_this_run": len(ordered_profiles),
        "modules": requested_modules,
        "registry": registry_metadata,
        "operations": operations,
        "validation": validation,
        "batch_modules": batch_reports,
        "third_party_cost_usd": 0,
        "request_budget": {**budget_snapshot, "plan": plan, "discovery_phase_started_with": discovery_start["remaining"],
                           "after_high_yield_discovery": discovery_end["remaining"], "after_low_yield_discovery": low_pass_end["remaining"],
                           "high_yield_companies": len(high_yield), "low_yield_companies": len(low_yield)},
        "contact_proofs_enabled": collisions is not None,
        "external_coverage": {
            "published_websites": sum(1 for p in ordered_profiles if any(c["field"] == "official_website" and c["availability"] == "available" for c in p["external_claims"])),
            "discovered_websites": sum(1 for p in ordered_profiles if (p["evidence"].get("website") or {}).get("source_class") == "discovered_company_website" and (p["evidence"]["website"].get("status") == "available")),
            "orgs_with_social": sum(1 for p in ordered_profiles if any(c["field"] in {"facebook", "instagram", "linkedin", "youtube", "x", "tiktok"} and c["availability"] == "available" for c in p["external_claims"])),
            "orgs_with_jobs": sum(1 for p in ordered_profiles if (p["evidence"].get("jobs") or {}).get("status") == "available"),
            "orgs_with_contact_email": sum(1 for p in ordered_profiles if any(c["field"] == "contact_email" for c in p["external_claims"])),
            "orgs_with_self_description": sum(1 for p in ordered_profiles if any(c["field"] == "self_description" for c in p["external_claims"])),
            "orgs_with_dated_activity": sum(1 for p in ordered_profiles if any(c["field"] == "dated_activity" and c["availability"] == "available" for c in p["external_claims"])),
            "orgs_with_feed_activity": sum(1 for p in ordered_profiles if any(c["field"] == "dated_activity" and c["availability"] == "available" and c.get("method") == "company_site_rss" for c in p["external_claims"])),
            "orgs_with_wikidata": sum(1 for p in ordered_profiles if (p["evidence"].get("wikidata") or {}).get("status") == "available"),
            "registry_sites_proven_by_discovery_gate": sum(1 for p in ordered_profiles if (p["evidence"].get("website") or {}).get("source_class") == "registry_linked_company_website"
                                                          and "deterministic_domain_discovery" in str((((p["evidence"].get("website") or {}).get("value") or {}).get("identity_assessment") or {}).get("method"))),
            "orgs_with_financials": sum(1 for p in ordered_profiles if (p["evidence"].get("financials") or {}).get("status") == "available"),
            "orgs_with_roles": sum(1 for p in ordered_profiles if (p["evidence"].get("roles") or {}).get("status") == "available"),
            "orgs_with_group": sum(1 for p in ordered_profiles if (p["evidence"].get("group") or {}).get("status") == "available"),
        },
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if validation["passed"] else 1)


if __name__ == "__main__":
    main()

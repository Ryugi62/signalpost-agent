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
from norway_company_agent.footprint.io import discover_website, nav_jobs_for_batch, registry_collisions, wikidata_for_batch  # noqa: E402


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
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--modules", default="registry,accounting_obligation,registry_live,financials,roles,group,locations,website,website_discovery,jobs,wikidata")
    parser.add_argument("--deadline-minutes", type=float, default=38.0, help="After this, remaining companies skip website crawling/discovery (envelopes still emitted)")
    parser.add_argument("--max-discovery-requests", type=int, default=1650, help="Hard cap on HTTP requests spent on domain discovery per run")
    parser.add_argument("--nav-days", type=int, default=75, help="NAV vacancy-feed window in days")
    args = parser.parse_args()

    started_at = utc_now()
    organisation_inputs = read_organisation_inputs(args.organisations)
    orgs = [item["organisation_number"] for item in organisation_inputs]
    if len(orgs) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} organisations, received {len(orgs)}")
    profiles, registry_metadata = profiles_from_bulk(args.bulk, orgs)
    annotations = {item["organisation_number"]: item for item in organisation_inputs}
    for profile in profiles:
        for key in ("evaluation_split", "sample_slice"):
            if key in annotations[profile["organisation_number"]]:
                profile[key] = annotations[profile["organisation_number"]][key]
    requested_modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    fetch_modules = set(requested_modules) - {"registry", "accounting_obligation", "website", "website_discovery", "jobs", "wikidata"}
    operations = {"requests": 0, "bytes": 0, "latencies_ms": [], "dns_lookups": 0, "by_module": {}}

    import threading
    import time as _time
    run_t0 = _time.monotonic()
    budget_lock = threading.Lock()
    discovery_spent = {"requests": 0}

    def over_deadline() -> bool:
        return (_time.monotonic() - run_t0) / 60.0 > args.deadline_minutes

    def enrich(profile: dict) -> tuple[dict, dict]:
        records, metrics = fetch_official_modules(profile["organisation_number"], fetch_modules)
        profile["evidence"].update(records)
        website_metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
        if "website" in requested_modules and over_deadline():
            from norway_company_agent.evidence import evidence as _ev
            profile["evidence"]["website"] = _ev("website", "source_error", "registry_linked_company_website", profile.get("website") or "about:blank", note="skipped: run deadline reached")
        elif "website" in requested_modules:
            website_record, website_metrics = fetch_website(profile.get("website"))
            profile["evidence"]["website"] = apply_website_identity_gate(profile, website_record)["website"]
        discovery_metrics = {"requests": 0, "bytes": 0, "latencies_ms": [], "dns_lookups": 0}
        if "website_discovery" in requested_modules:
            site = profile["evidence"].get("website") or {}
            published = site.get("status") == "available" and ((site.get("value") or {}).get("identity_assessment") or {}).get("publishable")
            if published:
                profile["evidence"]["website_discovery"] = {**site, "field": "website_discovery", "status": "not_applicable", "value": None,
                                                            "note": "Registry-linked website already passed the identity gate"}
            elif over_deadline() or discovery_spent["requests"] >= args.max_discovery_requests:
                from norway_company_agent.evidence import evidence as _ev
                profile["evidence"]["website_discovery"] = _ev("website_discovery", "source_error", "deterministic_domain_discovery", "about:blank",
                                                               note="skipped: run deadline or discovery request budget reached")
            else:
                try:
                    found, discovery, discovery_metrics = discover_website(profile, collisions=collisions)
                    with budget_lock:
                        discovery_spent["requests"] += discovery_metrics["requests"]
                except Exception as exc:  # never drop the envelope
                    from norway_company_agent.evidence import evidence as _ev
                    found, discovery = None, _ev("website_discovery", "source_error", "deterministic_domain_discovery", "about:blank", note=f"{type(exc).__name__}: {str(exc)[:160]}")
                profile["evidence"]["website_discovery"] = discovery
                if found:
                    if site.get("status") == "available":
                        profile["evidence"]["website_registry_unverified"] = site
                    profile["evidence"]["website"] = found
        metric = {
            "requests": len(metrics) + website_metrics["requests"] + discovery_metrics["requests"],
            "bytes": sum(item.bytes_received for item in metrics) + website_metrics["bytes"] + discovery_metrics["bytes"],
            "latencies_ms": [item.elapsed_ms for item in metrics] + website_metrics["latencies_ms"] + discovery_metrics["latencies_ms"],
            "dns_lookups": discovery_metrics.get("dns_lookups", 0),
            "discovery_requests": discovery_metrics["requests"],
            "website_requests": website_metrics["requests"],
        }
        profile["run_metrics"] = metric
        return profile, metric

    collisions = registry_collisions(args.bulk) if "website_discovery" in requested_modules else None
    nav_future = None
    nav_pool = None
    if "jobs" in requested_modules:
        from norway_company_agent.footprint.io import nav_active_entries
        nav_pool = ThreadPoolExecutor(max_workers=1)
        nav_future = nav_pool.submit(nav_active_entries, args.nav_days)
    state: dict[str, dict] = {}
    resumed_profiles = 0
    profiles_output = Path(args.profiles_output)
    if args.resume and profiles_output.exists():
        prior = [json.loads(line) for line in profiles_output.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not set(item["organisation_number"] for item in prior).issubset(set(orgs)):
            raise SystemExit("Resume profile membership is not a subset of this batch")
        state = {
            item["organisation_number"]: item
            for item in prior
            if profile_complete_for_modules(item, requested_modules)
        }
        resumed_profiles = len(state)
    pending_profiles = [profile for profile in profiles if profile["organisation_number"] not in state]
    # Spend the capped discovery budget where a site is most likely: staffed companies and registry e-mail first.
    def _priority(profile: dict) -> tuple:
        raw = ((profile.get("evidence") or {}).get("registry") or {}).get("value") or {}
        return (0 if profile.get("employees") else 1, 0 if "@" in str(raw.get("epostadresse") or "") else 1)
    pending_profiles.sort(key=_priority)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(enrich, profile): profile["organisation_number"] for profile in pending_profiles}
        for index, future in enumerate(as_completed(futures), 1):
            profile, metric = future.result()
            state[profile["organisation_number"]] = profile
            operations["requests"] += metric["requests"]
            operations["bytes"] += metric["bytes"]
            operations["latencies_ms"].extend(metric["latencies_ms"])
            operations["dns_lookups"] += metric.get("dns_lookups", 0)
            operations["by_module"]["website_discovery"] = operations["by_module"].get("website_discovery", 0) + metric.get("discovery_requests", 0)
            operations["by_module"]["website_registry"] = operations["by_module"].get("website_registry", 0) + metric.get("website_requests", 0)
            if index % args.checkpoint_every == 0 or index == len(pending_profiles):
                checkpoint = [state[org] for org in orgs if org in state]
                write_jsonl(profiles_output, checkpoint)

    ordered_profiles = [state[org] for org in orgs]
    batch_reports = {}
    if "wikidata" in requested_modules:
        wikidata, wikidata_metrics = wikidata_for_batch(orgs)
        for profile in ordered_profiles:
            profile["evidence"]["wikidata"] = wikidata[profile["organisation_number"]]
        operations["requests"] += wikidata_metrics["requests"]
        operations["by_module"]["wikidata"] = wikidata_metrics["requests"]
        batch_reports["wikidata"] = wikidata_metrics
    if "jobs" in requested_modules:
        job_orgs = {}
        for profile in ordered_profiles:
            locations = ((profile["evidence"].get("locations") or {}).get("value") or {}).get("locations") or []
            job_orgs[profile["organisation_number"]] = {
                "name": profile.get("name"),
                "subunits": [item.get("organisation_number") for item in locations if item.get("organisation_number")],
                "subunit_names": [item.get("name") for item in locations if item.get("name")],
            }
        jobs, jobs_metrics = nav_jobs_for_batch(job_orgs, days=args.nav_days, prefetched=nav_future)
        nav_pool.shutdown(wait=False)
        for profile in ordered_profiles:
            profile["evidence"]["jobs"] = jobs[profile["organisation_number"]]
        operations["requests"] += jobs_metrics.get("requests", 0)
        operations["by_module"]["jobs"] = jobs_metrics.get("requests", 0)
        batch_reports["jobs"] = jobs_metrics
    for profile in ordered_profiles:
        try:
            profile["external_claims"] = flatten_external_claims(profile)
        except Exception as exc:  # never lose the batch over one profile
            profile["external_claims"] = [{"field": "official_website", "value": None, "availability": "failed", "note": f"{type(exc).__name__}: {str(exc)[:120]}"},
                                          {"field": "job_postings", "value": None, "availability": "failed"}]
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
        "profiles_fetched_this_run": len(pending_profiles),
        "modules": requested_modules,
        "registry": registry_metadata,
        "operations": operations,
        "validation": validation,
        "batch_modules": batch_reports,
        "third_party_cost_usd": 0,
        "contact_proofs_enabled": collisions is not None,
        "external_coverage": {
            "published_websites": sum(1 for p in ordered_profiles if any(c["field"] == "official_website" and c["availability"] == "available" for c in p["external_claims"])),
            "discovered_websites": sum(1 for p in ordered_profiles if (p["evidence"].get("website") or {}).get("source_class") == "discovered_company_website" and (p["evidence"]["website"].get("status") == "available")),
            "orgs_with_social": sum(1 for p in ordered_profiles if any(c["field"] in {"facebook", "instagram", "linkedin", "youtube", "x", "tiktok"} and c["availability"] == "available" for c in p["external_claims"])),
            "orgs_with_jobs": sum(1 for p in ordered_profiles if (p["evidence"].get("jobs") or {}).get("status") == "available"),
            "orgs_with_wikidata": sum(1 for p in ordered_profiles if (p["evidence"].get("wikidata") or {}).get("status") == "available"),
        },
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if validation["passed"] else 1)


if __name__ == "__main__":
    main()

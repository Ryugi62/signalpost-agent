# 100-company smoke test (v2; v1 tables kept below)

- Input: `smoke-companies.jsonl`, 100 random organisations from the public 411,160-company universe (`select_entry_batch.py --seed 20261004`).
- Result: **100/100 terminal envelopes**, `validation.passed = true`, run time about 5 min, $0 third-party cost. Most of the time is the NAV feed walk, done once per batch in parallel with the per-company work.
- A viewer built from this run is at `site/index.html`.

| Same 100 companies | Builderr starter (unchanged) | This agent |
|---|---:|---:|
| Published exact company websites | 5 | **12** (7 discovered with on-site proof) |
| Companies with verified social profiles | 2 | **4** |
| Companies with a company role mailbox / self-description (verified site) | 0 / 0 | **7 / 9** |
| Companies with active NAV vacancies (by org number) | 0 | **2** |
| Companies with dated activity on their own site | 0 | **1** |
| HTTP requests | 568 | 915 |

## v2 (request gate, feed activity, JSON-LD profiles)

- Smoke 100 (same companies), run twice with the one command into the same output: 100/100 envelopes each (5 min 9 s, 5 min 3 s) · **395 requests per run in total** (v1: 915) · 12 websites (6 discovered) · 3 with social · 2 with NAV jobs · 1 with dated activity (site feed) · 99/100 with annual accounts. The second run compared all 100 profiles with the first (`profile.refresh`): **0 changes, 0 fields not compared**, and the first run's profiles were kept as `smoke-profiles.before-smoke-100-v2-run1.jsonl` (idempotent refresh, prior snapshot preserved). `smoke-report-first-run.json` is the first run's report, `smoke-report.json` the second's.

Same fixed batch (seed 20261013, 1,000 companies), companies with each external field:

| | v1 (host re-run) | **v2 default** (strict: ≤1,950 requests in total, registry included; final code, clean container) | v2 `--budget-scope external` (≤1,950 third-party requests, registry reads not capped; rc2 code — identity rules as final) |
|---|---:|---:|---:|
| Official website | 77 | 49 | **84** |
| Social profiles (companies / links) | 30 / 54 | 19 / 36 | **34 / 65** |
| NAV jobs | 3 | 3 | 3 |
| Dated activity | 3 | 4 | **6** |
| Annual accounts | all (per-company calls) | 998 | 998 |
| Requests: total / non-registry (sites, NAV, Wikidata) | 7,304 / 2,304 | **1,943 / 839** | 2,999 / 1,928 |

The strict default gives up part of the website budget to keep every company's annual accounts inside 1,950 requests. If Builderr confirms that registry reads are not counted, `--budget-scope external` is the better setting on every external field.

## Fresh 1,000-company batches (frozen code, clean Linux container `python3.12-bookworm`, `uv sync --frozen`)

| Batch | Starter (unchanged) | This agent |
|---|---|---|
| seed 20261008 (tag v1-rc2) | **crashes**: 2 org numbers absent from the bulk snapshot. Without them (998): 44 websites, 16 with social | 1,000/1,000 envelopes in 8 min 54 s · 91 websites (38 discovered) · 33 with social · 5 with NAV jobs |
| seed 20261009 (tag v1-rc3) | **crashes**: 3 org numbers absent from the bulk snapshot | 1,000/1,000 envelopes in 10 min 1 s · 108 websites (51 discovered) · 46 with social · 9 with NAV jobs · 7,114 requests (discovery 1,536, NAV 161, Wikidata 3) |
| seed 20261010 (v1-rc5, host run) | **crashes**: 1 org number absent from the bulk snapshot | 1,000/1,000 envelopes in 7 min 24 s · 94 websites (50 discovered) · 45 with social · 4 with NAV jobs · 6 with dated activity · 7,231 requests (discovery 1,682, NAV 145, Wikidata 3) |

| seed 20261011 (v1-rc5 tag, clean container) | **crashes**: 3 absent org numbers | 1,000/1,000 in 8 min 46 s · 92 websites (34 discovered) · 39 with social |
| seed 20261012 (v1-rc6, clean container) | **crashes**: 1 absent org number | 1,000/1,000 in 9 min 3 s · 89 websites (38 discovered) · 53 with role mailbox · 61 with self-description |
| seed 20261013 (**final v1**, clean container) | runs (no absent org numbers in this batch) | 1,000/1,000 in 9 min 41 s · 74 websites (35 discovered) · 28 with social · 39 with role mailbox · 41 with self-description · 7,301 requests (discovery 1,753, NAV 145, Wikidata 3) |

`../local-1000-run-report.json` is the final-code run (seed 20261013, clean `python3.12-bookworm` container, `uv sync --frozen`). The identity audit is in `../identity-audit.md`.

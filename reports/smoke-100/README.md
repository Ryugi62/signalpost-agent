# 100-company smoke test (v1)

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

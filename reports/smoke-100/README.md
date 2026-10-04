# 100-company smoke test (v1, tag v1-rc3)

- Input: `smoke-companies.jsonl`, 100 random organisations from the public 411,160-company universe (`select_entry_batch.py --seed 20261004`).
- Result: **100/100 terminal envelopes**, `validation.passed = true`, run time 4 min 58 s, $0 third-party cost. Most of the time is the NAV feed walk, done once per batch in parallel with the per-company work.
- A viewer built from this run is at `site/index.html`.

| Same 100 companies | Builderr starter (unchanged) | This agent |
|---|---:|---:|
| Published exact company websites | 5 | **11** (6 discovered with on-site proof) |
| Companies with verified social profiles | 2 | **3** |
| Companies with active NAV vacancies (by org number) | 0 | **2** |
| HTTP requests | 568 | 820 |

## Fresh 1,000-company batches (frozen code, clean Linux container `python3.12-bookworm`, `uv sync --frozen`)

| Batch | Starter (unchanged) | This agent |
|---|---|---|
| seed 20261008 (tag v1-rc2) | **crashes**: 2 org numbers absent from the bulk snapshot. Without them (998): 44 websites, 16 with social | 1,000/1,000 envelopes in 8 min 54 s · 91 websites (38 discovered) · 33 with social · 5 with NAV jobs |
| seed 20261009 (tag v1-rc3) | **crashes**: 3 org numbers absent from the bulk snapshot | 1,000/1,000 envelopes in 10 min 1 s · 108 websites (51 discovered) · 46 with social · 9 with NAV jobs · 7,114 requests (discovery 1,536, NAV 161, Wikidata 3) |

`../local-1000-run-report.json` is the seed 20261009 run report. The identity audit is in `../identity-audit.md`.

# 100-company smoke test (v1)

- Input: `smoke-companies.jsonl`, 100 random organisations from the public 411,160-company universe (`select_entry_batch.py --seed 20261004`).
- Result: **100/100 terminal envelopes**, `validation.passed = true`, run time 4 min 57 s (8 of the 100 companies were website crawls; the NAV feed walk runs in parallel), $0 third-party cost.

| Same 100 companies | Builderr starter (unchanged) | This agent |
|---|---:|---:|
| Published exact company websites | 5 | **12** (7 found by domain discovery with on-site proof) |
| Companies with verified social profiles | 2 | **4** |
| Companies with active NAV vacancies (by org number) | 0 | **2** |
| HTTP requests | 568 | 825 |

Local 1,000-company test (`../local-1000-run-report.json`, different seed): 1,000/1,000 envelopes in 7 min 8 s. Published websites 120 (62 discovered), companies with social profiles 56, NAV jobs 3, Wikidata matches 16. A hand audit of the discovered sites rejected directory, parent-group and redirect cases, and the gate was tightened to match (see `SPEC.md` and the tests).

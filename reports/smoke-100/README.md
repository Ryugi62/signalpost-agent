# 100-company smoke test (final v1)

- Input: `smoke-companies.jsonl`, 100 random organisations from the public 411,160-company universe (`select_entry_batch.py --seed 20261004`).
- Result: **100/100 terminal envelopes**, `validation.passed = true`, run time 4 min 54 s, $0 third-party cost. Most of the run time is the once-per-batch NAV feed walk, which runs in parallel with the per-company work.

## The same companies, unchanged Builderr starter vs this agent

| 100-company smoke batch | Starter | This agent |
|---|---:|---:|
| Published exact company websites | 5 | **11** (6 found by domain discovery with on-site proof) |
| Companies with verified social profiles | 2 | **3** |
| Companies with active NAV vacancies (matched by org number) | 0 | **2** |
| HTTP requests | 568 | 829 |

| Local 1,000-company batch (seed 20261007, `../local-1000-run-report.json`) | Starter | This agent |
|---|---:|---:|
| Published exact company websites | 47 | **118** (63 discovered) |
| Companies with verified social profiles | 24 | **50** |
| Companies with active NAV vacancies | 0 | **2** |
| Companies with a Wikidata org-number match | 0 | **9** |
| Run time / HTTP requests | 5 min 44 s / 5,648 | 7 min 48 s / 7,218 (discovery 1,604, NAV 146, Wikidata 3) |

`../identity-audit.md` covers the audit of the discovered sites.

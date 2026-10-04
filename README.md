# Signalpost exact-ID footprint agent

Entry for the Builderr **Signalpost** challenge. It is built on the official Builderr reference agent (starter kit) and keeps its registry, financials, roles, subunits, evidence records, refresh replay and terminal envelopes. It adds three external modules, each tied to the **organisation number** rather than to name similarity:

| Module | Field family | Identity rule | Source / licence |
|---|---|---|---|
| `website_discovery` | official website, plus the company-owned social profiles it links to | Candidates: the domain of the company's **registry e-mail address** (free-mail and any domain shared with another registry entity are excluded), then `.no` hostnames generated from the legal name, subunit names and å/ø spellings. Publication requires one of three proofs. **Org proof:** the exact 9-digit organisation number on a fetched page of that site, where that page shows no other org number. **Contact proof:** the full legal name plus a registry phone or registry street+postcode that **only this entity holds in the whole registry**. **Registry e-mail domain** (held by this entity only): the starter's registry-website name gate. A single legal-name token shorter than 4 letters never passes on name alone. Contact and e-mail proofs fail closed (org proof only) when the bulk snapshot is partial (<1M rows) or lacks the needed columns. Redirects to other domains are accepted only onto a root-level page with an org proof. Contact proofs are refused when a legal-name qualifier such as "Norway" or "Group" is missing from the domain, because that is likely a parent or brand site. Everything else stays `ambiguous` and is never published. No search engine is used. | the company's own site (robots.txt respected) |
| `jobs` | hiring: active vacancies | The NAV ad's `employer.orgnr` equals the organisation or one of its registered subunits. Expired ads are dropped. | NAV public vacancy feed `pam-stilling-feed.nav.no` (public token fetched at run time) |
| `wikidata` | social IDs (corroboration) | Wikidata P2333 (Norwegian organisation number) equals the organisation, and exactly one item carries it. Its social IDs are published only when the item's P856 website matches the verified company site; otherwise they are `ambiguous`. | Wikidata SPARQL, CC0 |

The starter's website identity gate now also reads footer and contact text, so a registry-listed site that prints its org number in the footer is no longer withheld. Organisation numbers missing from the bulk snapshot (deleted since) still get a terminal envelope instead of crashing the batch.

**Identity audit.** On two fresh 1,000-company batches that were not used for tuning, every discovered site was checked against its stored proof snippet (`reports/identity-audit.md`). Each published claim carries `proof_snippet`, `identity_reason`, `source_url`, `retrieved_at` and `content_sha256`.

## Synthesis and UX

- **Cited company brief** (`profile.company_brief`): a deterministic summary built from the final claims. It covers what the company is, its latest filed accounts, official leadership, workplaces, verified website and profiles, and hiring. **Every sentence carries its source URL and retrieval time.** A separate `unknowns` list gives each missing topic and what was checked, for example "No website could be tied to this exact entity; checked: registry website field; foo.no: no_dns". No language model is used, missing values are never turned into zero, and absence is never stated as fact: the brief says "no website verified", not "no website".
- **Viewer** (`scripts/build_prototype.py --input out/profiles.jsonl --output site/index.html`): the starter's static company explorer, extended with a "Company brief" panel, NAV vacancies (linked to the ad) and verified social profiles. It provides search, filters and pinning, and has an "Ask this company" panel that answers only from the record. Checked at 390 px (no horizontal scroll) and 1280 px. A built copy for the smoke batch is in `reports/smoke-100/site/index.html`.
- Annual-account records are ordered latest-first, so every view shows the latest filing. The starter showed the oldest of three.

## One command (official run)

```bash
uv sync --frozen && uv run python scripts/run_competition_batch.py \
  --organisations <batch.jsonl> --bulk <brreg-enheter.csv> \
  --profiles-output out/profiles.jsonl --output out/envelopes.jsonl \
  --report out/run-report.json --run-id <id> --expected-count <N>
```

`--bulk` is the Brønnøysund bulk snapshot (`https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv`). Every input returns exactly one terminal envelope. `profile.external_claims` lists every external field with an explicit availability state (`available`, `not_available`, `ambiguous`, `blocked`, `failed`).

- Models and APIs: **no LLM and no paid API.** Brønnøysund open data (NLOD 2.0), NAV public vacancy feed, Wikidata (CC0) and company-owned websites.
- Secrets: none. Third-party cost per official run: **$0**.
- Budget: the NAV feed is read once per batch (~140 pages for 75 days), in parallel with the per-company work. Wikidata is one SPARQL request per 400 companies. Domain discovery runs DNS first and fetches at most 3 candidate sites (≤3 pages each), and only for companies without a verified registry website. It is hard-capped by `--max-discovery-requests` (default 1,650). After `--deadline-minutes` (default 38), the remaining companies skip crawling but still return envelopes. Per-module request counts go into the run report. The registry modules are the starter's unchanged per-company calls. A local 1,000-company run takes about 8 minutes.
- Smoke test: `reports/smoke-100/` (100 random companies from the public universe).

---

# Signalpost reference agent

This is a runnable starting point for the Signalpost company-research challenge. It is intentionally a solid baseline, not a winning submission.

The public universe contains 411,160 eligible companies. Run the starter on 100 companies before submitting. Larger local tests, including 1,000 or more companies, are encouraged but their precomputed profiles are not submitted or scored.

## What it already does

- reads a batch of Norwegian organisation numbers;
- anchors identity in the Brønnøysund bulk registry;
- fetches official financials, roles, group links and registered workplaces;
- visits the registry-listed website and rejects weak entity matches;
- emits one terminal JSONL envelope per input;
- records sources, retrieval times, content hashes, request counts and latency;
- supports checkpoint/resume and a deterministic refresh replay;
- includes examples for external-footprint discovery and an evidence-bounded research agent.

## First run: try one saved example

Requires Python 3.12+. Open a terminal inside this extracted folder.

Before downloading company data or running a full crawl, try the bundled public
sample. It uses saved responses: no API key, registry download or live web requests.

```bash
python3 scripts/run_refresh_replay.py \
  --manifest tests/fixtures/refresh-snapshots.json \
  --output out/refresh-demo.json
```

Open `out/refresh-demo.json`. The `events` list shows what changed between two
versions of one company profile and the source evidence for each change. The sample
should find two expected changes, no false changes, and no extra changes when the
same data is checked again.

The report's `qualification_passed` field refers only to this public sample check.
It does not qualify an entry for the competition or prove live information coverage.
The printed request counts are reads from saved responses, not network calls.

## Next: research live companies

Requires Python 3.12+ and `uv`. This step downloads data and makes live requests.
The manifest selector can create a local test batch of any size. Use 100 rows for the recommended smoke test before trying a larger batch.

```bash
uv sync
curl -L 'https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv' -o brreg-enheter.csv
curl -L 'https://builderr.ai/signalpost-company-universe-2025.jsonl.gz' -o signalpost-universe.jsonl.gz

uv run python select_entry_batch.py \
  --universe signalpost-universe.jsonl.gz \
  --count 100 \
  --output entry-companies.jsonl

# Use the 100-company batch as your smoke test.
cp entry-companies.jsonl smoke-companies.jsonl

uv run python scripts/run_competition_batch.py \
  --organisations smoke-companies.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/smoke-profiles.jsonl \
  --output out/smoke-envelopes.jsonl \
  --report out/smoke-report.json \
  --run-id smoke-001 \
  --expected-count 100

# You may test at larger scale locally, but Builderr supplies the official batch for scoring.
uv run python scripts/run_competition_batch.py \
  --organisations entry-companies.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl \
  --output out/envelopes.jsonl \
  --report out/run-report.json \
  --run-id local-001 \
  --expected-count 1000

uv run --with pytest pytest -q
```

The published archive was clean-room verified on August 24, 2026: 104 tests and 5 subtests passed, followed by a one-company live BRREG smoke run with one terminal envelope, five requests and zero silent drops.

Increase `--count` and `--expected-count` together for a larger local test. The 100-row smoke test above is practice only; Builderr supplies the companies for every official run.

## The improvement loop

1. Treat the organisation number as the anchor.
2. Generate site/profile candidates from official data, the company site, lawful search providers and named people.
3. Save every candidate and the evidence for or against it.
4. Publish only exact-entity matches. Parent, brand, franchise and similarly named companies are not exact.
5. Crawl static HTML first. Escalate to a browser only when a deterministic completeness check fails.
6. Measure added supported coverage, wrong-company claims, runtime, requests and cost.
7. Promote a strategy only when it improves coverage without weakening the accuracy gates.
8. Freeze strategies and thresholds before the daily evaluation run.

The strongest differentiator is external evidence that remains exact and auditable: official company pages, company-owned profiles, jobs, dated activity, ratings/reviews and permitted public signals. Do not trade accuracy for volume.

## Important source rule

Open-source code does not grant permission to scrape a platform. Follow each source's terms, robots policy, rate limits and licence. LinkedIn, Meta and Indeed are useful identity/discovery targets, but direct automated collection may be restricted. Use permitted APIs, licensed providers, company-owned outbound links, or return `blocked`/`not_available`.

Read `docs/competition-control-loop.md`, `docs/external-connectors.md` and the public source policy before adding connectors.

## Submission contract

Submit a repository with:

- a 100-company smoke-test result or report;
- one documented command that accepts a JSONL batch of organisation numbers;
- exactly one terminal envelope per input;
- pinned dependencies and reproducible setup;
- a previous-snapshot input and material-change output;
- a machine-readable run report with runtime, request count and third-party cost;
- declared models, APIs, licences and source-rights assumptions.

Email the repository URL, run command, models/APIs and expected cost per 100-company run to `submit@builderr.ai`.

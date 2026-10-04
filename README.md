# Signalpost exact-ID footprint agent

Entry for the Builderr **Signalpost** challenge. It is built on the official Builderr reference agent (starter kit) and keeps its registry, financials, roles, subunits, evidence records, refresh replay and terminal envelopes. It adds three external modules, each tied to the **organisation number** rather than to name similarity:

| Module | Field family | Identity rule | Source / licence |
|---|---|---|---|
| `website_discovery` | official website, plus the company-owned social profiles it links to | Candidates: websites declared on the company's **registered subunits**, the domain of its **registry e-mail address** (free-mail and any domain shared with another registry entity are excluded), then `.no` hostnames generated from the legal name, subunit names and å/ø spellings, and finally `<name>.com`, which only an org-number proof can publish. Publication requires one of two proofs (the registry e-mail domain is only a candidate source, never a proof). **Org proof:** the exact 9-digit organisation number on a fetched page of that site, where that page shows no other org number. **Contact proof:** the full legal name plus a registry phone or registry street+postcode that **only this entity holds in the whole registry**. It is allowed only on a `.no` domain spelled like the full legal name. A registry-declared domain with another label, such as a group or law-firm site, needs the org number. A single legal-name token shorter than 4 letters never passes on name alone (registry-website gate). Contact proofs and e-mail candidates fail closed (org proof only) when the bulk snapshot is partial (<1M rows) or lacks the needed columns. Redirects to other domains are accepted only onto a root-level page with an org proof. Contact proofs are refused when a legal-name qualifier such as "Norway" or "Group" is missing from the domain, because that is likely a parent or brand site. Everything else stays `ambiguous` and is never published. No search engine is used. | the company's own site (robots.txt respected) |
| `jobs` | hiring: active vacancies | The NAV ad's `employer.orgnr` equals the organisation or one of its registered subunits. Expired ads are dropped. | NAV public vacancy feed `pam-stilling-feed.nav.no` (public token fetched at run time) |
| `dated_activity` | dated public activity | Only from a site that already passed the identity gate. Covers JSON-LD `NewsArticle`/`Article`/`Event` items and `<article>` blocks with a `<time datetime>` on the fetched pages (no extra request), and **(v2) the posts feed the site declares in its own `<link rel="alternate">`** (RSS/Atom on the same domain, one request; read only on a `.no` site or a site with an org-number proof, so a parent group's `.com` news is never attributed to a subsidiary). Feed posts need a date within the last 730 days and a link on the site's domain; CMS placeholders and site-builder sample posts are dropped. SEO page metadata (`#webpage`) and protected posts are dropped. | the verified company site |
| `social profiles` | company-owned profiles | Footer/page links and **(v2) the site's own JSON-LD `Organization.sameAs`** on a verified site; a profile is published only when its handle carries the legal name (same gate for both). No extra requests. | the verified company site |
| `contact_email`, `self_description` | company contact and "what it does" | Only from a verified site. Contact e-mails must be role mailboxes (post@, info@, kontakt@ …) on the company's own domain; personal addresses are never published. The self-description is the site's own meta description, labelled as company-owned promotional copy. No extra requests. | the verified company site |
| `wikidata` | social IDs (corroboration) | Wikidata P2333 (Norwegian organisation number) equals the organisation, and exactly one item carries it. Its social IDs are published only when the item's P856 website matches the verified company site; otherwise they are `ambiguous`. | Wikidata SPARQL, CC0 |

The starter's website identity gate now also reads footer and contact text, so a registry-listed site that prints its org number in the footer is no longer withheld. Organisation numbers missing from the bulk snapshot (deleted since) still get a terminal envelope instead of crashing the batch.

**Identity audit** (`reports/identity-audit.md`): every discovered site in fresh 1,000-company batches was read (URL, proof type, proof span). v2 rules: 0 wrong entities in 41 discoveries from two batches never seen before (seeds 20261014–20261015); the audit also fixed two feed-activity cases (site-builder sample posts; a parent group's `.com` news). v1 rules: 0 wrong in 35 held-out discoveries, and 0 wrong + 1 questionable brand site (rejected by the final rule) across five frozen-code audits with 208 discoveries. The audits were done by the author, not an independent reviewer. Each published claim carries `proof_snippet`, `identity_reason`, `source_url`, `retrieved_at` and `content_sha256`.

**Starter examples not used.** `scripts/` still holds the starter kit's optional examples (LinkedIn guest pages, Google News RSS, Google Maps result normaliser, Fagfolkguiden reviews, Brave and YouTube search, a sentiment model). The official command imports none of them and makes no request to those services; they are kept unchanged from the starter for reference only. In envelopes, each module carries the starter's terminal `state` plus `availability` in the contract's six states.

## Synthesis and UX

- **Cited company brief** (`profile.company_brief`): a deterministic summary built from the final claims. It covers what the company is, what it says it does (its own words, labelled), its latest filed accounts and the change from the previous filing, official leadership, workplaces, verified website and profiles, and hiring. **Every sentence carries its source URL and retrieval time.** A separate `unknowns` list gives each missing topic and what was checked, for example "No website could be tied to this exact entity; checked: registry website field; foo.no: no_dns". No language model is used, missing values are never turned into zero, and absence is never stated as fact: the brief says "no website verified", not "no website".
- **Viewer** (`scripts/build_prototype.py --input out/profiles.jsonl --output site/index.html`): the starter's static company explorer, extended with a "Company brief" panel, NAV vacancies (linked to the ad) and verified social profiles. It provides search, filters and pinning, and has an "Ask this company" panel that answers only from the record. Checked at 390 px (no horizontal scroll) and 1280 px. A built copy for the smoke batch is in `reports/smoke-100/site/index.html`.
- Annual-account records are ordered latest-first, so every view shows the latest filing. The starter showed the oldest of three.

## One command (official run)

```bash
uv sync --frozen && uv run python scripts/run_competition_batch.py \
  --organisations <batch.jsonl> --bulk <brreg-enheter.csv> \
  --profiles-output out/profiles.jsonl --output out/envelopes.jsonl \
  --report out/run-report.json --run-id <id> --expected-count <N>
```

Refresh: run the same command again with the same `--profiles-output`, or pass `--previous <earlier profiles.jsonl>` (needed in a clean directory). Each profile then carries `refresh` (changes since that run; fields one run could not read are listed as `not_compared`, never as changes), and the earlier file is kept as `<name>.before-<run_id>.jsonl`. Page text read for identity checks is not written to the output (staff names and phone numbers stay out); profiles keep URLs, titles, hashes, proof snippets and claims.

`--bulk` is the Brønnøysund bulk snapshot (`https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv`). Every input returns exactly one terminal envelope. `profile.external_claims` lists every external field with an explicit availability state (`available`, `not_available`, `ambiguous`, `blocked`, `failed`).

- Models and APIs: **no LLM and no paid API.** Sources are Brønnøysund open data (NLOD 2.0), NAV's public vacancy feed (open data from arbeidsplassen.nav.no, read with the token NAV publishes at `/api/publicToken`), Wikidata (CC0) and company-owned websites (robots.txt honoured, identifying User-Agent). From company sites only short proof spans and hashes are stored. Ad contact persons and personal phone numbers are never published.
- Secrets: none. Third-party cost per official run: **$0**.
- **Request budget (v2, hard).** Every outbound HTTP request of a run — registry, company sites, robots.txt, redirect hops, retries, NAV, Wikidata — passes one gate (`http_gate.py`, wrapping `http.client` `putrequest`) that refuses the request *before it is sent* once the run has spent `--max-outbound-requests` (default **1,950**). This meets the strictest reading of the published "2,000 outbound requests" daily limit (registry calls included); the Builderr contract itself says only "a fixed time and resource budget", so the reading is not settled. Spending order: batch registry reads (entity search 300 per request, the two Brønnøysund bulk files for roles and workplaces), Wikidata (1 per 400), NAV feed (45-day window, ~100 pages, 97% of active ads), registry-declared websites, the posts feed of verified sites, then discovery; a **registry reserve** (one annual-accounts request per company + 4% for retries + group structure for `erIKonsern` entities) is set aside before any website work, so every company keeps its latest filed accounts. A refused request leaves an explicit `blocked` record with a policy note, never a dropped envelope. Exact per-category counts are in the run report (`request_budget`). `--budget-scope external` counts registry reads without capping them (for the reading in which the limit covers third-party sources only). After `--deadline-minutes` (default 38) the remaining companies skip crawling but still return envelopes.
- Smoke test: `reports/smoke-100/` (100 random companies from the public universe; v2 code, run twice: 100/100 envelopes in about 5 min 10 s, 395 requests per run in total; the second run reports 0 changes against the first; plus a viewer build). Fresh 1,000-company run of the final code: `reports/local-1000-run-report.json`, a clean `python3.12-bookworm` Linux container with `uv sync --frozen`, the test suite (198 passed) and the one command: **1,000/1,000 in 5 min 32 s, 1,943 requests in total** (annual accounts 1,035 · registry websites 438 · discovery 287 · NAV 99 · group 63 · feeds 12 · registry batch/bulk 6 · Wikidata 3). This is the fixed batch (seed 20261013) used for every before/after comparison; identity audits use batches never seen before. More batches are listed in `reports/smoke-100/README.md`.
- Robustness: organisation numbers missing from the bulk snapshot still get envelopes. The unchanged starter raised an exception for this reason on 6 of the 9 random 1,000-company batches tested locally.

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

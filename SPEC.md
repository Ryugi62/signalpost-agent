# SPEC — Signalpost exact-ID footprint agent (v1)

## 0. Purpose
Raise **external recall** (the only separating axis on the Builderr Signalpost board, 4 Oct 2026: best 17.67/50, 0 of 23 entries qualified) without adding wrong-company publications. It is built on the official Builderr starter kit, which already provides the registry, financials, roles, subunits, the registry-website crawl, evidence records and terminal envelopes.

## 1. Success conditions (numbers)
- S1: 100-company smoke run returns **100/100 terminal envelopes**, `validation.passed = true`.
- S2: **0 wrong-company publications** in a hand audit of every discovered website (no registry website) in the smoke run.
- S3: Published exact websites in the smoke run are at least **1.3×** the starter's (registry-only) count on the same batch.
- S4: External requests (discovery + jobs + Wikidata) are **≤ 2 per company on average**, and the whole run takes **≤ 45 min per 1,000 companies** at the default workers.
- S5: Third-party cost is **$0**, with no credential tied to the entrant's own account.

## 2. Non-goals
No paid search API, no LLM calls in the official run, no scraping of LinkedIn/Meta/Glassdoor/Indeed, and no personal data beyond the public company roles the registry already publishes.

## 3. Ubiquitous language
- **organisation number (org)**: the 9-digit Brønnøysund key, used as the identity anchor.
- **subunit**: an official underenhet (workplace) of an org.
- **domain candidate**: a `.no` hostname generated deterministically from the legal name. It is not evidence.
- **org proof**: the exact 9-digit org (with or without spaces/dots) appears on a fetched page of the candidate site, and that page shows no other org number (this excludes directories and group lists).
- **contact proof**: every legal-name token appears, **and** the registry phone or the registry street+postcode appears, **and** that phone or address is held by exactly one entity in the bulk registry. It is refused when the site lists other org numbers, or when a legal-name qualifier such as Norway/Group/Holding is absent from the domain.
- **registry e-mail domain**: the domain of the registry `epostadresse`. Free-mail is excluded, and so is any domain shared by more than 3 entities. It has the same standing as a registry website.
- **discovered website**: a candidate that passed org proof or contact proof. Only a discovered website is published.
- **job claim**: an active NAV (arbeidsplassen) vacancy whose `employer.orgnr` equals the org or one of its subunits.
- **wikidata bridge**: a Wikidata item whose P2333 equals the org. It yields its website (P856) and social IDs.

## 4. Model
`ExternalClaim{field, value, availability, source_url, source_class, retrieved_at, effective_at, content_sha256, method}`. Each module returns evidence records in the starter's `evidence()` shape.

## 5. Use cases
- UC-1 Domain discovery: for an org whose registry website is missing or not publishable → candidates → DNS → fetch (robots, homepage, ≤2 secondary pages) → proof gate → publish as `evidence.website` (source_class `discovered_company_website`), or record `ambiguous` candidates under `evidence.website_discovery`.
- UC-2 NAV jobs: walk the public NAV vacancy feed (If-Modified-Since, N days) once per batch → match `businessName` to batch legal or subunit names → fetch each match's detail → keep only the ads whose `employer.orgnr` is in {org} ∪ subunits → `evidence.jobs`.
- UC-3 Wikidata bridge: one SPARQL query per batch (VALUES of orgs) → `evidence.wikidata` (website, facebook, instagram, linkedin, youtube, x).
- UC-4 Claims: flatten all external evidence into `profile.external_claims` (OUTPUT_CONTRACT shape) with explicit availability.

## 6. Acceptance criteria (Given/When/Then)
- AC-1 Given "SANDNES ELEKTRISKE AS", when candidates are generated, then they include `sandneselektriske.no` and `sandnes-elektriske.no`, and no candidate contains legal-form tokens.
- AC-2 Given page text "Org.nr: 810 034 882" and org 810034882, then the proof is `org`. Given another 9-digit number, the proof is `none`.
- AC-3 Given all name tokens plus the registry postcode and street on the page, then the proof is `contact`. Given the name tokens only, the proof is `none` (ambiguous, not published).
- AC-4 Given a NAV detail whose employer.orgnr is a subunit of org X, then the job is attributed to X. Given an unrelated orgnr, it is rejected.
- AC-5 Given a SPARQL binding with P2333 = X, then the claims carry the website and social URLs with the source `https://www.wikidata.org/wiki/Q…`.
- AC-6 Every input org yields exactly one envelope, even when the discovery, NAV or Wikidata modules fail (state `source_error`, never dropped), and even when the org is absent from the bulk snapshot.
- AC-7 A redirect to a different domain is published only when it lands on a root-level page with an org proof (directory deep links are rejected).
- AC-8 A phone shared by 2 or more registry entities never proves identity.

## 7. Layers
`src/norway_company_agent/footprint/` holds pure functions (candidates, proof, matching, parsing), which are domain logic with no I/O. The I/O adapters (DNS/HTTP/NAV/Wikidata) sit in the same package's `*_io.py`. The runner script is the infrastructure.

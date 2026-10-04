# Identity audit of discovered websites

**Question.** For a company with no verified registry website, is every website that `website_discovery` publishes the company's own site?

**Method.** Two fresh random 1,000-company batches from the public universe (seeds 20261006 and 20261007) were used. Neither was used while the rules were written. For every published discovered site, I read the final URL, the proof type and the stored proof snippet. Then I judged whether the site belongs to the exact legal entity, rather than to a parent, a brand owner, a directory or a namesake.

| Batch | Discovered and published | Org proof | Name + unique phone | Name + unique address | Registry e-mail domain | Wrong entity | Questionable |
|---|---:|---:|---:|---:|---:|---:|---:|
| seed 20261006 | 58 | 36 | 8 | 5 | 9 | 0 | 1 |
| seed 20261007 | 64 | 41 | 13 | 3 | 7 | 0 | 1 |

There were two questionable cases. Each one led to a stricter rule, and both cases are now rejected:

1. **ENRY NORWAY AS → enry.com.** The registry e-mail domain is the international brand site. **Rule:** when a legal-name qualifier (Norway/Norge/Nordic/Europe/Group/Holding/…) is missing from the domain, only an org-number proof is accepted.
2. **FJORDSAILING AS → fjordsailing.no.** The page shows two org numbers in a 3-2-4 digit grouping. **Rule:** detection of other org numbers now accepts any digit grouping, so a page that lists several org numbers never proves identity.

An earlier, unfrozen 1,000-company run turned up four cases. Each one shaped a rule:

- a directory listing (`vvseksperten.no/rorlegger/...`);
- a cluster-organisation page (`kunnskapsbyen.no/...`);
- a parent group (`sandegruppen.no`);
- a parent brand (`realkapital.no` for REALKAPITAL PROSJEKT AS).

The resulting rules are:

- **Off-candidate redirects:** accepted only onto a root-level page with an org proof.
- **Contact proofs:** the phone or address must be held by exactly one entity in the bulk registry. This rejects shopping-centre addresses, accountants' phones and shared offices.
- **Org proofs:** the page must show no other org number.

## Frozen-code audits (clean Linux container, new seeds)

| Batch / tag | Discovered and published | Org proof | Unique phone | Unique address | Registry e-mail + name gate | Wrong entity |
|---|---:|---:|---:|---:|---:|---:|
| seed 20261008 / v1-rc2 | 38 | 25 | 5 | 4 | 4 | **1** |
| seed 20261009 / v1-rc3 | 51 | 39 | 7 | 5 | 0 (path removed) | **0** |
| seed 20261010 / v1-rc5 | 50 | 41 | 5 | 4 | 0 | **0** |
| seed 20261011 / v1-rc5 (container) | 34 | 27 | 7 (phone + address) | — | 0 | **0** |
| seed 20261012 / v1-rc6 (container) | 38 | 22 | 16 (phone + address) | — | 0 | **0 wrong, 1 questionable**: CONFECTA AS → confecta.com, the brand's international site, proven by a unique phone → v1-rc7: `.com` needs the org number |
| seed 20261013 / **final v1** (container) | 35 | 22 | 13 (phone + address) | — | 0 | **0** |

The one wrong case was **CARLBERGVEIEN 7 AS → personalpartner.no**. A holding company named after its street address had registered its owner's e-mail domain, and that owner's homepage shows the address. Fix in v1-rc3: the registry e-mail domain is now only a candidate source. Publishing still needs an org proof or a registry-unique contact proof, and the shared address fails uniqueness.


**v1-rc4 check (seed 20261009 re-run).** There were 3 new discoveries from subunit-declared websites. Two of them were group or firm sites proven only by a unique phone: GAIA LISTA AS → gaiaarkitekter.no and ADVOKATFIRMAET KATRALEN → advokatenebk.no. Fix in v1-rc5: contact proofs are accepted only on a domain spelled like the full legal name. Any other registry-declared domain needs the org number.

**Result (earlier rules).** 0 wrong-entity publications among 122 audited discoveries. The 95% upper bound on the error rate is about 2.5% (rule of three). Under the current rules the 2 questionable cases are rejected as well.

**Final rules (v1):** 0 wrong among the 35 discoveries of a batch never seen before (seed 20261013). Across the last five frozen audits (seeds 20261009–20261013, 208 discoveries) there were 0 wrong entities and 1 questionable brand site, which the final rule rejects. The audit was done by the author, reading the URL and the proof span. It was not an independent second reviewer.

**Privacy.** Snippets for org proofs keep only about 40 characters around the number, and e-mail addresses are masked. Contact proofs store only a short hash of the matched phone or address, never the value. Personal names and contact persons from company pages are not published.

## v2 audits (strict request budget, feed activity, JSON-LD profiles)

v2 changes the discovery path (homepage-first page budget, registry-declared sites re-checked with the proof gate at no request cost, declared domains with another label need the org number) and adds two claim sources on verified sites: the site's own RSS/Atom posts feed and its JSON-LD `sameAs` profiles. Two batches never seen before were run and every published discovery was read (URL, title, proof type, proof span):

| Batch / code | Budget scope | Discovered and published | Org proof | Unique phone or address | Wrong entity | Other findings → rule |
|---|---|---:|---:|---:|---:|---|
| seed 20261014 / fd7bd69 | external (registry reads not capped, to get ≥35 discoveries through the same identity code) | 35 | 23 | 12 | **0** | Wix sample posts on a verified church site ("Tips for writing great posts…") → site-builder sample posts are dropped from feed activity |
| seed 20261015 / 95c15ab | strict (default) | 6 | 5 | 1 | **0** | PLASMAN AS → plasman.com (registry-declared `.com` group site, name gate): its feed is the parent group's news → feeds are read only on `.no` sites or sites with an org-number proof |
| seed 20261013 (fixed comparison batch) / 71c95bf final | strict (default), clean container | 9 | 6 | 3 | **0** | — |

**Result (v2 rules).** 0 wrong entities among 41 discoveries in two new batches (and 0 among the 9 of the final-code run on the fixed batch). After the review, dated activity is attributed only from sites with an org-number or registry-unique contact proof, or a `.no` domain spelled like the full legal name (AC-28). For the 22 companies with dated activity in the two batches, the three newest items of each were read; after the two fixes above, every item read is a dated post on the company's own site. JSON-LD profiles pass the same handle gate as footer links; on four earlier batches the gate admitted 0–11 extra profiles per batch and rejected parent/manager profiles (for example `alti-forvaltning-as` for SANDAKER SENTER AS, `peab-asfalt-norge` for SWEROCK AS). Author audit, not an independent reviewer.

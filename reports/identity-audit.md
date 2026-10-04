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

**Result.** 0 wrong-entity publications among 122 audited discoveries. The 95% upper bound on the error rate is about 2.5% (rule of three). Under the current rules the 2 questionable cases are rejected as well.

**Privacy.** Snippets for org proofs keep only about 40 characters around the number, and e-mail addresses are masked. Contact proofs store only the matched phone or address value. Personal names and contact persons from company pages are not published.

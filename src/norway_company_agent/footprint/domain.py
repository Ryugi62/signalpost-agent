"""Pure footprint logic: no network, no framework imports (SPEC §7)."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

LEGAL_FORMS = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "nuf", "ks", "bbl", "brl",
    "ba", "ab", "gmbh", "ltd", "limited", "inc", "plc", "aps", "oy", "bv",
}
STOP = {"og", "the", "and", "i", "pa", "av", "for", "til"}
_TRANS = str.maketrans({"ø": "o", "Ø": "o", "å": "a", "Å": "a", "æ": "ae", "Æ": "ae", "&": " og "})
SEP = r"[\s.\- ]?"


def _ascii(value: Any) -> str:
    text = str(value or "").translate(_TRANS)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def name_tokens(name: Any) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", _ascii(name)) if t not in LEGAL_FORMS]


def name_key(name: Any) -> str:
    return " ".join(name_tokens(name))


def _label_ok(base: str) -> bool:
    return 3 <= len(base) <= 63 and not base.isdigit() and not base.startswith("-") and not base.endswith("-")


def _alt_ascii_tokens(name: Any) -> list[str]:
    """Second spelling for Norwegian letters (å→aa, ø→oe, æ→ae), used only when the name contains them."""
    raw = str(name or "")
    if not any(ch in raw for ch in "åÅøØ"):
        return []
    text = raw.translate(str.maketrans({"ø": "oe", "Ø": "oe", "å": "aa", "Å": "aa", "æ": "ae", "Æ": "ae", "&": " og "}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [t for t in re.findall(r"[a-z0-9]+", text) if t not in LEGAL_FORMS and t != "og"]


def domain_candidates(name: Any, *, limit: int = 4, brand_names: Iterable[Any] = ()) -> list[str]:
    """Deterministic .no hostnames from the legal name (and registered subunit names). Candidates, never evidence."""
    tokens = [t for t in name_tokens(name) if t not in {"og"}]
    if not tokens:
        return []
    bases = ["".join(tokens), "-".join(tokens)]
    for brand in brand_names:
        brand_tokens = [t for t in name_tokens(brand) if t not in {"og", "avd", "avdeling"}]
        if brand_tokens and brand_tokens != tokens:
            bases.append("".join(brand_tokens))
    alt = _alt_ascii_tokens(name)
    if alt and alt != tokens:
        bases.append("".join(alt))
    if len(tokens) > 2:
        bases += ["".join(tokens[:2]), "-".join(tokens[:2])]
    out: list[str] = []
    for base in bases:
        if _label_ok(base):
            host = f"{base}.no"
            if host not in out:
                out.append(host)
    if _label_ok(bases[0]) and len(bases[0]) >= 6:
        out.append(f"{bases[0]}.com")  # last resort; the same on-site proof gate applies
    return out[:limit]


FREE_MAIL = {
    "gmail.com", "googlemail.com", "online.no", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.no", "live.com",
    "yahoo.no", "yahoo.com", "c2i.net", "lyse.net", "me.com", "icloud.com", "mac.com", "broadpark.no", "frisurf.no", "start.no",
    "msn.com", "getmail.no", "altibox.no", "tele2.no", "chello.no", "bluezone.no", "sensewave.com", "ebnett.no", "haugnett.no",
    "loqal.no", "monet.no", "vikenfiber.no", "netcom.no", "telia.no", "ice.no", "protonmail.com", "proton.me", "aol.com", "gmx.com",
    "mail.com", "yandex.com", "pm.me", "hotmail.se", "live.se",
}


def email_domain_candidate(email: Any, shared_counts: dict[str, int] | None = None, *, max_shared: int = 1) -> str | None:
    """Registry-declared e-mail domain as a site candidate; free-mail and shared (manager/accountant/group) domains excluded."""
    text = str(email or "").strip().casefold()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[1].strip(". ")
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain) or domain in FREE_MAIL:
        return None
    if shared_counts is None or shared_counts.get(domain, 0) > max_shared:
        return None  # fail closed: without registry-wide counts, sharing cannot be ruled out
    return domain


def _digits_pattern(digits: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\d)" + SEP.join(re.escape(d) for d in digits) + r"(?!\d)")


def _phone_digits(phone: Any) -> str | None:
    digits = re.sub(r"\D", "", str(phone or ""))
    if digits.startswith("0047"):
        digits = digits[4:]
    elif digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    return digits if len(digits) == 8 else None


ORG_LIKE = re.compile(r"(?<!\d)[89](?:[\s.\u00a0]?\d){8}(?!\d)")


def _other_org_numbers(org: str, text: str) -> set[str]:
    found = {re.sub(r"\D", "", m) for m in ORG_LIKE.findall(text)}
    found.discard(org)
    return found


ROLE_MAILBOXES = {"post", "info", "kontakt", "contact", "firmapost", "salg", "sales", "booking", "kundeservice", "service",
                  "support", "ordre", "order", "bestilling", "resepsjon", "hello", "hei", "mail", "office", "kontor", "admin", "faktura"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _snippet(text: str, match: re.Match[str]) -> str:
    """Short evidence span around the proof; e-mail addresses are masked (no personal contact data in output)."""
    span = re.sub(r"\s+", " ", text[max(0, match.start() - 30): match.end() + 10]).strip()
    return re.sub(r"\S*@\S*", "[e-mail]", span)  # full or cut-off addresses


def address_key(street: Any, postcode: Any) -> str | None:
    tokens = [t for t in re.findall(r"[a-z0-9]+", _ascii(street)) if t not in {"postboks", "pb"}]
    code = re.sub(r"\D", "", str(postcode or ""))
    return f"{' '.join(tokens)}|{code}" if tokens and len(code) == 4 else None


def identity_proof(
    profile: dict[str, Any],
    page_texts: Iterable[str],
    *,
    allow_contact: bool = True,
    collisions: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Exact-entity proof for a candidate site. Returns proof in {org, contact, none} and the matched snippet.

    - org: the exact org number appears on a page that shows no other org number (rules out directories/group lists).
    - contact (only when allow_contact): all legal-name tokens + a registry phone or street+postcode that is held by
      exactly one registry entity (collisions), and the page lists no other org number.
    allow_contact=False is used for truncated/brand candidates, where only the org number may prove identity."""
    texts = [str(t or "") for t in page_texts]
    joined = "\n".join(texts)
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    if len(org) == 9:
        pattern = _digits_pattern(org)
        for text in texts:
            match = pattern.search(text)
            if match and not _other_org_numbers(org, text):
                return {"proof": "org", "reason": "exact organisation number on a fetched page of the candidate site (no other org number on that page)", "snippet": _snippet(text, match)}
        if pattern.search(joined):
            return {"proof": "none", "reason": "org number appears only on a page listing other org numbers (directory or group page)"}
    if not allow_contact:
        return {"proof": "none", "reason": "truncated-name candidate requires the exact organisation number"}
    if collisions is None:
        return {"proof": "none", "reason": "registry-wide collision counts unavailable; only an org-number proof is accepted (fail closed)"}
    tokens = [t for t in name_tokens(profile.get("name")) if t not in STOP]
    compact_page = re.sub(r"[^a-z0-9]", "", _ascii(joined))
    if not tokens or not all(t in compact_page for t in tokens):
        return {"proof": "none", "reason": "legal-name tokens not all present"}
    if _other_org_numbers(org, joined):
        return {"proof": "none", "reason": "site pages list other org numbers; name+contact proof not accepted"}
    reg = profile.get("registry") or {}
    personal = str(profile.get("legal_form") or "").upper() in {"ENK", ""}  # a sole proprietor's phone/address is personal data
    phones = (collisions or {}).get("phone") or {}
    addresses = (collisions or {}).get("address") or {}
    phone = _phone_digits(reg.get("phone"))
    if phone and (collisions is None or phones.get(phone, 0) == 1):
        match = _digits_pattern(phone).search(joined)
        if match:
            span = (re.sub(r"\s+", " ", match.group(0)) + " [= registry phone]") if not personal else \
                "registry phone matched (value withheld; sole proprietorship; sha256 " + __import__("hashlib").sha256(phone.encode()).hexdigest()[:12] + ")"
            return {"proof": "contact", "reason": "legal name + registry phone (unique to this entity in the registry) on a fetched page", "snippet": span}
    postcode = re.sub(r"\D", "", str(reg.get("postcode") or ""))
    street_tokens = [t for t in re.findall(r"[a-z]{3,}", _ascii(reg.get("street"))) if t not in {"postboks", "pb"}]
    key = address_key(reg.get("street"), reg.get("postcode"))
    if (
        len(postcode) == 4
        and street_tokens
        and (collisions is None or (key and addresses.get(key, 0) == 1))
        and all(t in compact_page for t in street_tokens)
    ):
        match = re.search(r"(?<!\d)" + postcode + r"(?!\d)", joined)
        if match:
            span = (" ".join(street_tokens).title() + " … " + match.group(0) + " [= registry street + postcode]") if not personal else \
                "registry street+postcode matched (value withheld; sole proprietorship; sha256 " + __import__("hashlib").sha256(str(key).encode()).hexdigest()[:12] + ")"
            return {"proof": "contact", "reason": "legal name + registry street and postcode (unique to this entity in the registry) on a fetched page", "snippet": span}
    return {"proof": "none", "reason": "name matches but no unique org number, phone or address corroboration"}


def match_jobs_to_orgs(details: Iterable[dict[str, Any]], orgs: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    owner: dict[str, str] = {}
    for org, info in orgs.items():
        owner[org] = org
        for sub in info.get("subunits") or []:
            owner.setdefault(str(sub), org)
    out: dict[str, list[dict[str, Any]]] = {}
    for detail in details:
        employer_org = str((detail.get("employer") or {}).get("orgnr") or "")
        parent = owner.get(employer_org)
        if parent:
            out.setdefault(parent, []).append(detail)
    return out


WIKIDATA_FIELDS = {
    "website": ("official_website", "{}"),
    "facebook": ("facebook", "https://www.facebook.com/{}"),
    "instagram": ("instagram", "https://www.instagram.com/{}/"),
    "linkedin": ("linkedin", "https://www.linkedin.com/company/{}/"),
    "youtube": ("youtube", "https://www.youtube.com/channel/{}"),
    "x": ("x", "https://x.com/{}"),
}


def parse_wikidata_bindings(bindings: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for row in bindings:
        org = re.sub(r"\D", "", (row.get("org") or {}).get("value", ""))
        item = (row.get("item") or {}).get("value", "")
        qid = item.rsplit("/", 1)[-1]
        if len(org) != 9 or not qid.startswith("Q"):
            continue
        for key, (field, template) in WIKIDATA_FIELDS.items():
            raw = (row.get(key) or {}).get("value")
            if not raw:
                continue
            value = template.format(raw.strip())
            out.setdefault(org, {})[(field, value)] = {
                "field": field,
                "value": value,
                "availability": "available",
                "source_url": f"https://www.wikidata.org/wiki/{qid}",
                "source_class": "wikidata_cc0_org_number_match",
                "method": "wikidata_P2333_exact_org_number",
            }
    # An org number carried by more than one Wikidata item is ambiguous: publish nothing for it.
    items_per_org: dict[str, set[str]] = {}
    for org, claims in out.items():
        items_per_org[org] = {c["source_url"] for c in claims.values()}
    return {org: list(v.values()) for org, v in out.items() if len(items_per_org[org]) == 1}


def _state(status: str | None) -> str:
    return {
        "available": "available",
        "not_found": "not_available",
        "not_applicable": "not_applicable",
        "blocked": "blocked",
        "ambiguous": "ambiguous",
        "source_error": "failed",
    }.get(str(status or ""), "failed")


SHARED_HOSTS = {"wixsite.com", "blogspot.com", "wordpress.com", "github.io", "squarespace.com", "webflow.io", "netlify.app",
                "vercel.app", "herokuapp.com", "weebly.com", "jimdofree.com", "jimdosite.com", "business.site", "mozello.com"}


def _reg_domain(url: Any) -> str:
    """Registrable domain; on shared site-builder hosts the tenant label is kept (foo.wixsite.com != bar.wixsite.com)."""
    host = re.sub(r"^https?://", "", str(url or "").casefold()).split("/")[0].split(":")[0]
    parts = [p for p in host.split(".") if p and p != "www"]
    if len(parts) >= 3 and ".".join(parts[-2:]) in SHARED_HOSTS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def activity_allowed(value: dict[str, Any], name: Any, *, in_group: bool = False) -> bool:
    """Whether a verified site's own news may be attributed to this exact entity (dated activity, feed): the site
    carries the org number or a registry-unique contact proof, or it is a .no domain spelled like the full legal name.
    A registry-declared group or brand site (hyr.no for HYR BERGEN AS, plasman.com for PLASMAN AS) passes the website
    gate as the company's declared site, but its news is the group's."""
    assessment = value.get("identity_assessment") or {}
    method = str(assessment.get("method") or "")
    reasons = " ".join(str(r) for r in assessment.get("reasons") or [])
    if "org_proof" in method or "contact_proof" in method or any(str(r).startswith("exact organisation number") for r in assessment.get("reasons") or []):
        return True
    if in_group:
        return False  # part of a registered group: a name-spelled domain may still be the group's shared site, so a proof is needed
    domain = str(value.get("registered_domain") or _reg_domain(value.get("final_url")))
    label = domain.split(".")[0].replace("-", "")
    tokens = [t for t in name_tokens(name) if t != "og"]
    return domain.endswith(".no") and bool(tokens) and label == "".join(tokens)


def in_registered_group(profile: dict[str, Any]) -> bool:
    ev = profile.get("evidence") or {}
    live = (ev.get("registry_live") or {}).get("value") or {}
    raw = (ev.get("registry") or {}).get("value") or {}
    flag = live.get("in_group") if isinstance(live, dict) else None
    if flag is None and isinstance(raw, dict):
        flag = str(raw.get("erIKonsern") or "").casefold() in {"true", "1", "ja"}
    return bool(flag)


def flatten_external_claims(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Claim-level view (OUTPUT_CONTRACT shape) for the external field families."""
    ev = profile.get("evidence") or {}
    claims: list[dict[str, Any]] = []
    site = ev.get("website") or {}
    value = site.get("value") or {}
    assessment = value.get("identity_assessment") or {}
    if site.get("status") == "available" and assessment.get("publishable"):
        claims.append({
            "field": "official_website", "value": value.get("final_url") or site.get("source_url"),
            "availability": "available", "source_url": site.get("source_url"),
            "source_class": site.get("source_class"), "retrieved_at": site.get("retrieved_at"),
            "content_sha256": site.get("content_sha256"), "method": assessment.get("method"),
            "identity_reason": "; ".join(assessment.get("reasons") or []),
            "proof_snippet": assessment.get("proof_snippet"),
            "date_basis": "retrieved_at (live company page; no publication date)",
        })
        if not activity_allowed(value, profile.get("name"), in_group=in_registered_group(profile)):
            claims[-1]["site_relationship"] = ("declared by this entity in the registry; the domain is not spelled like its legal name and the site shows "
                                               "no org number, so it may be a group or brand site (its news is not attributed to this entity)")
        activity: dict[tuple[str, str], dict[str, Any]] = {}
        allowed = activity_allowed(value, profile.get("name"), in_group=in_registered_group(profile))
        site_domain = _reg_domain(value.get("final_url") or site.get("source_url"))
        name_titles = {re.sub(r"[^a-z0-9]+", " ", _ascii(profile.get("name"))).strip(), " ".join(name_tokens(profile.get("name")))}
        withheld = 0
        feed = value.get("feed_activity") or {}
        feed_source = {"url": feed.get("feed_url"), "dated_activity": feed.get("items") or [], "retrieved_at": feed.get("retrieved_at"),
                       "content_sha256": feed.get("content_sha256")}
        for source in [value, *(value.get("pages") or []), feed_source]:
            for item in source.get("dated_activity") or []:
                title_key = re.sub(r"[^a-z0-9]+", " ", _ascii(item.get("title"))).strip()
                if title_key in name_titles or (item.get("url") and _reg_domain(item.get("url")) != site_domain):
                    continue  # a page named after the company, or an item hosted elsewhere, is not dated activity of this site
                if not allowed:
                    withheld += 1
                    continue
                activity.setdefault((item.get("date"), str(item.get("title")).casefold()),
                                    {**item, "page": source.get("url") or value.get("final_url"),
                                     "retrieved_at": source.get("retrieved_at") or site.get("retrieved_at"), "page_sha256": source.get("content_sha256")})
        # A bilingual site lists each post twice (/post/x and /en/post/x-translated): keep the primary-language copies.
        LANG = re.compile(r"^/(en|de|sv|da|fr|es|nl|fi|pl)(/|$)")
        def _path(item: dict[str, Any]) -> str:
            return re.sub(r"^https?://[^/]+", "", str(item.get("url") or ""))
        if any(LANG.match(_path(i)) for i in activity.values()) and any(not LANG.match(_path(i)) for i in activity.values()):
            activity = {k: v for k, v in activity.items() if not LANG.match(_path(v))}
        for item in sorted(activity.values(), key=lambda x: x.get("date") or "", reverse=True)[:10]:
            from_feed = item.get("method") == "rss"
            claim = {
                "field": "dated_activity", "value": {"title": item.get("title"), "date": item.get("date"), "type": item.get("type"), "url": item.get("url")},
                "availability": "available", "source_url": item.get("page"), "source_class": "verified_company_site_dated_item",
                "retrieved_at": item.get("retrieved_at"), "effective_at": item.get("date"), "method": f"company_site_{item.get('method')}",
                "date_basis": ("publication date stated in the verified company site's own RSS/Atom feed" if from_feed
                               else "publication/start date stated on the company page"),
            }
            if from_feed and item.get("page_sha256"):
                claim["content_sha256"] = item["page_sha256"]
            claims.append(claim)
        feed_state = (value.get("feed_activity") or {})
        if not activity and allowed and value.get("feed_link") and (not feed_state or feed_state.get("skipped") or feed_state.get("error")):
            unread = "blocked" if (not feed_state or feed_state.get("skipped") or "budget" in str(feed_state.get("error")).casefold()) else "failed"
            claims.append({"field": "dated_activity", "value": None, "availability": unread, "source_url": value.get("feed_link"),
                           "retrieved_at": feed_state.get("retrieved_at") or site.get("retrieved_at"),
                           "note": f"The site's own feed was not read in this run ({feed_state.get('skipped') or feed_state.get('error') or 'request budget or run deadline (policy)'})"})
        elif not activity:
            note = ("The verified site is a registry-declared group or brand site (no org number on it, domain not spelled like the legal name); "
                    f"its {withheld} dated item(s) are not attributed to this entity" if withheld else
                    "No dated article/event markup on the fetched pages of the verified site, and no dated post in its own feed")
            claims.append({"field": "dated_activity", "value": None, "availability": "not_available", "source_url": value.get("final_url"),
                           "retrieved_at": site.get("retrieved_at"), "note": note})
        description = str(value.get("description") or "").strip()
        if len(description) >= 30:
            claims.append({
                "field": "self_description", "value": description[:400], "availability": "available",
                "source_url": value.get("final_url") or site.get("source_url"), "source_class": "company_owned_promotional_copy",
                "retrieved_at": site.get("retrieved_at"), "content_sha256": site.get("content_sha256"),
                "method": "verified_site_meta_description", "date_basis": "retrieved_at (live company page)",
                "note": "Company's own description of its business; not an independent assessment",
            })
        domain = _reg_domain(value.get("final_url") or site.get("source_url"))
        emails: dict[str, str] = {}
        for source in [value, *(value.get("pages") or [])]:
            for match in EMAIL_RE.findall(str(source.get("identity_text_excerpt") or "")):
                local, _, host = match.casefold().partition("@")
                if local in ROLE_MAILBOXES and _reg_domain("https://" + host) == domain:
                    emails.setdefault(match.casefold(), source.get("url") or value.get("final_url"))
        for address, page in list(emails.items())[:3]:
            claims.append({
                "field": "contact_email", "value": address, "availability": "available", "source_url": page,
                "source_class": "verified_company_site_contact", "retrieved_at": site.get("retrieved_at"),
                "content_sha256": next((pg.get("content_sha256") for pg in [value, *(value.get("pages") or [])] if (pg.get("url") or pg.get("final_url")) == page), site.get("content_sha256")),
                "method": "role_mailbox_on_verified_site", "date_basis": "retrieved_at (live company page)",
                "note": "Generic company mailbox on the company's own domain; personal addresses are never published",
            })
        if len(description) < 30:
            claims.append({"field": "self_description", "value": None, "availability": "not_available", "source_url": value.get("final_url"),
                           "retrieved_at": site.get("retrieved_at"), "note": "The verified site has no meta description"})
        if not emails:
            claims.append({"field": "contact_email", "value": None, "availability": "not_available", "source_url": value.get("final_url"),
                           "retrieved_at": site.get("retrieved_at"), "note": "No generic company mailbox on the company's own domain on the fetched pages"})
        if not value.get("social_links"):
            claims.append({"field": "social_profiles", "value": None, "availability": "not_available", "source_url": value.get("final_url"),
                           "retrieved_at": site.get("retrieved_at"),
                           "note": "No company-owned profile whose handle carries the legal name is linked from the verified site"})
        else:
            claims.append({"field": "social_profiles", "value": [link.get("url") for link in value.get("social_links") or []], "availability": "available",
                           "source_url": value.get("final_url") or site.get("source_url"), "retrieved_at": site.get("retrieved_at"),
                           "note": "Summary row; one claim per profile follows (field = platform)"})
        for link in value.get("social_links") or []:
            claims.append({
                "field": link.get("platform"), "value": link.get("url"), "availability": "available",
                "source_url": value.get("final_url") or site.get("source_url"),
                "source_class": "verified_company_site_outbound_link", "retrieved_at": site.get("retrieved_at"),
                "content_sha256": site.get("content_sha256"), "method": "company_site_social_link",
                "date_basis": "retrieved_at of the verified company page that links to the profile",
            })
    else:
        discovery = ev.get("website_discovery") or {}
        attempts = ((discovery.get("value") or {}).get("attempts") or []) if isinstance(discovery.get("value"), dict) else []
        budget_stop = discovery.get("status") == "blocked" or any(a.get("result") == "run_request_budget_exhausted" for a in attempts)
        if site.get("status") == "available" or discovery.get("status") == "ambiguous":
            state = "ambiguous"
        elif budget_stop or site.get("status") == "blocked":
            state = "blocked"  # not checked (request-budget policy or robots.txt), which is not the same as "nothing there"
        else:
            state = _state(site.get("status") or "not_found")
        claims.append({"field": "official_website", "value": None, "availability": state,
                       "source_url": site.get("source_url") or discovery.get("source_url"),
                       "retrieved_at": site.get("retrieved_at") or discovery.get("retrieved_at"),
                       "checked": ["registry website field"] + [f"{a.get('candidate')}: {a.get('result')}" for a in attempts],
                       "note": ("Not checked: " + str(discovery.get("note") or site.get("note") or "request-budget policy") if state == "blocked" else
                                "A candidate site was found but it does not prove this exact entity (no org number or registry-unique contact); withheld, see 'checked'." if state == "ambiguous" else
                                "Not found by the methods listed in 'checked' as of retrieved_at; uncertain matches are withheld.")})
        for family in ("social_profiles", "dated_activity", "contact_email", "self_description"):
            claims.append({"field": family, "value": None, "availability": "blocked" if state == "blocked" else "not_available",
                           "source_url": None, "retrieved_at": site.get("retrieved_at") or discovery.get("retrieved_at"),
                           "note": f"Read only from a verified company site; none verified for this entity (website: {state})"})
    jobs = ev.get("jobs") or {}
    items = (jobs.get("value") or {}).get("items") or [] if isinstance(jobs.get("value"), dict) else []
    if jobs.get("status") == "available" and items:
        for job in items:
            claims.append({
                "field": "job_postings", "value": {k: job.get(k) for k in ("title", "published", "expires", "workplace", "employer_orgnr")},
                "availability": "available", "source_url": job.get("url"), "source_class": "nav_public_vacancy_feed",
                "retrieved_at": jobs.get("retrieved_at"), "effective_at": job.get("published"), "expires_at": job.get("expires"),
                "date_basis": "NAV ad published/expires dates",
                "content_sha256": job.get("content_sha256"), "method": "nav_employer_orgnr_exact",
            })
    else:
        claims.append({"field": "job_postings", "value": None, "availability": _state(jobs.get("status") or "not_found"),
                       "source_url": jobs.get("source_url"), "retrieved_at": jobs.get("retrieved_at")})
    wikidata = ev.get("wikidata") or {}
    wd_claims = ((wikidata.get("value") or {}).get("claims") or []) if isinstance(wikidata.get("value"), dict) else []
    verified_site = next((c["value"] for c in claims if c["field"] == "official_website" and c["availability"] == "available"), None)
    wd_site = next((c["value"] for c in wd_claims if c["field"] == "official_website"), None)
    corroborated = bool(verified_site and wd_site and _reg_domain(verified_site) == _reg_domain(wd_site))
    have = {(c["field"], c.get("value")) for c in claims if isinstance(c.get("value"), str)}
    for claim in wd_claims:
        if claim["field"] == "official_website" or (claim["field"], claim["value"]) in have:
            continue
        # Wikidata social IDs are published only when the item's own website matches the verified company site.
        claims.append({**claim, "availability": "available" if corroborated else "ambiguous",
                       "retrieved_at": wikidata.get("retrieved_at"), "content_sha256": wikidata.get("content_sha256"),
                       "corroboration": f"Wikidata P856 {wd_site} matches verified site" if corroborated else "not corroborated by a verified company site",
                       "date_basis": "retrieved_at of the Wikidata SPARQL response (CC0)"})
    return claims


# --- Dated activity from the verified site's own RSS/Atom feed (AC-22, AC-23) ---------------------------

FEED_TYPES = ("application/rss+xml", "application/atom+xml")
PLACEHOLDER_TITLES = {
    "hello world", "hei verden", "hallo verden", "sample page", "eksempelside", "om oss", "about", "about us", "kontakt",
    "kontakt oss", "contact", "contact us", "home", "hjem", "forside", "uncategorized", "ukategorisert", "test", "personvern",
    "privacy policy", "personvernerklaering", "cookies", "get to know us",
}
# Sample posts that site builders (Wix, Squarespace, WordPress themes) ship with a new blog; matched as phrases.
TEMPLATE_PHRASES = (
    "keep in touch with site visitors", "tips for writing great posts", "make the most of the season", "design a stunning blog",
    "grow your blog community", "showcase your work", "spread the word", "expand your reach", "your blog post title",
    "this is your blog post", "welcome to your blog", "this is the title of your first post", "first blog post", "lorem ipsum",
)
FEED_WINDOW_DAYS = 730


def feed_link(html: str, page_url: str) -> str | None:
    """The site's own posts feed declared in <link rel="alternate">: RSS/Atom only (no oEmbed), not a comments feed,
    and on the page's registered domain (a third-party feed host is never followed)."""
    from html.parser import HTMLParser
    import urllib.parse

    found: list[str] = []

    class _Links(HTMLParser):
        def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
            if tag != "link":
                return
            a = {k.casefold(): (v or "") for k, v in attrs}
            if "alternate" not in a.get("rel", "").casefold().split() or a.get("type", "").casefold() not in FEED_TYPES:
                return
            href = a.get("href", "").strip()
            label = (href + " " + a.get("title", "")).casefold()
            if not href or "comment" in label or "kommentar" in label:
                return
            found.append(urllib.parse.urljoin(page_url, href))

    try:
        _Links().feed(str(html or "")[:400_000])
    except Exception:
        return None
    site = _reg_domain(page_url)
    for url in found:
        if urllib.parse.urlparse(url).scheme in {"http", "https"} and _reg_domain(url) == site:
            return url
    return None


def _feed_date(value: str) -> str | None:
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime

    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def parse_feed_items(xml_text: str, *, feed_url: str, site_domain: str, now: str, limit: int = 10) -> list[dict[str, Any]]:
    """Posts from an RSS 2.0 or Atom feed. Kept: a title, a parseable date within the last FEED_WINDOW_DAYS days (not in
    the future), a link on the site's own registered domain. Dropped: theme/CMS placeholders (Hello world, lorem ipsum,
    page names such as 'Om oss') and repeated titles. Never raises."""
    import urllib.parse
    import xml.etree.ElementTree as ET
    from datetime import datetime, timedelta

    try:
        root = ET.fromstring(str(xml_text or "")[:1_000_000].encode("utf-8"))
    except Exception:
        return []
    now_dt = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
    oldest = (now_dt - timedelta(days=FEED_WINDOW_DAYS)).isoformat()
    newest = (now_dt + timedelta(days=1)).isoformat()
    site = _reg_domain("https://" + str(site_domain or ""))
    items: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        title, date, link = "", None, ""
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "title":
                title = re.sub(r"\s+", " ", "".join(child.itertext())).strip()
            elif tag in {"pubDate", "published", "date"} or (tag == "updated" and date is None):
                date = _feed_date("".join(child.itertext())) or date
            elif tag == "link":
                href = child.get("href")
                if href is not None:
                    if child.get("rel") in (None, "alternate") and not link:
                        link = href
                elif not link:
                    link = "".join(child.itertext()).strip()
        if not title or not date or not (oldest <= date <= newest):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", _ascii(title)).strip()
        if not key or key in PLACEHOLDER_TITLES or key.startswith("lorem ") or any(phrase in key for phrase in TEMPLATE_PHRASES):
            continue
        url = urllib.parse.urljoin(feed_url, link) if link else ""
        if not url or _reg_domain(url) != site:
            continue
        item = {"title": title[:200], "date": date[:10], "type": "feed_post", "url": url, "method": "rss", "published_at": date}
        if key not in items or items[key]["published_at"] < date:
            items[key] = item
    return sorted(items.values(), key=lambda x: x["published_at"], reverse=True)[:limit]

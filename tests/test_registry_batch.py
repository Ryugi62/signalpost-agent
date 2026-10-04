"""UC-6 registry reads that fit the request budget (SPEC §6 AC-13..AC-16). Fixtures only; no network."""
import gzip
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.registry_batch import (  # noqa: E402
    entity_batch_urls,
    iter_role_elements,
    live_records_from_batch,
    subunits_from_csv,
)


def test_ac13_entity_batch_urls_cover_every_org_in_chunks():
    orgs = [str(810000000 + i) for i in range(650)]
    urls = entity_batch_urls(orgs, chunk=300)
    assert len(urls) == 3
    joined = ",".join(u.split("organisasjonsnummer=")[1].split("&")[0] for u in urls)
    assert joined.split(",") == orgs
    assert all("size=" in u for u in urls)


def test_ac13_live_records_mark_missing_orgs_not_found():
    body = {"_embedded": {"enheter": [{"organisasjonsnummer": "810034882", "navn": "SANDNES ELEKTRISKE AS", "telefon": "51 00 00 00",
                                        "erIKonsern": True, "organisasjonsform": {"kode": "AS"}, "aktivitet": ["Elektro."]}]}}
    records = live_records_from_batch(["810034882", "999999999"], body, retrieved_at="2026-10-05T00:00:00Z", batch_url="https://x/?q")
    assert records["810034882"]["status"] == "available"
    assert records["810034882"]["value"]["phone"] == "51 00 00 00"
    assert records["810034882"]["value"]["in_group"] is True
    assert records["810034882"]["source_url"] == "https://data.brreg.no/enhetsregisteret/api/enheter/810034882"
    assert records["810034882"]["content_sha256"]
    assert records["999999999"]["status"] == "not_found"


CSV = (
    '"organisasjonsnummer","navn","naeringskode1.kode","naeringskode1.beskrivelse","antallAnsatte","hjemmeside","epostadresse",'
    '"beliggenhetsadresse.adresse","beliggenhetsadresse.poststed","beliggenhetsadresse.postnummer","beliggenhetsadresse.kommune",'
    '"beliggenhetsadresse.kommunenummer","beliggenhetsadresse.land","beliggenhetsadresse.landkode","overordnetEnhet"\n'
    '"973409948","SANDNES ELEKTRISKE AS AVD BRYNE","43.210","Elektrisk","4","www.sandnes-el.no","post@sandnes-el.no","Storgata 1",'
    '"BRYNE","4340","TIME","1121","Norge","NO","810034882"\n'
    '"973409949","OTHER AVD","43.210","Elektrisk","","","","Vei 2","OSLO","0150","OSLO","0301","Norge","NO","999888777"\n'
)


def test_ac14_subunits_from_bulk_csv_only_for_batch_orgs():
    out = subunits_from_csv(io.StringIO(CSV), {"810034882"})
    assert list(out) == ["810034882"]
    loc = out["810034882"][0]
    assert loc["organisation_number"] == "973409948"
    assert loc["website"] == "www.sandnes-el.no"
    assert loc["email_domain"] == "sandnes-el.no"
    assert "email" not in loc  # the address itself is not kept
    assert loc["address"]["kommune"] == "TIME" and loc["address"]["postnummer"] == "4340"
    assert loc["employees"] == 4


def test_ac15_role_elements_stream_split_and_filter():
    elements = [
        {"organisasjonsnummer": "810034882", "rollegrupper": [{"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"}, "sistEndret": "2016-07-11",
                                                             "roller": [{"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                                                                         "person": {"fodselsdato": "1981-09-27", "navn": {"fornavn": "Morten", "etternavn": "A"}}}]}]},
        {"organisasjonsnummer": "999888777", "rollegrupper": []},
    ]
    # The Brreg file closes each element with a line "}," at column 0; emulate that layout.
    text = "[\n" + "\n},\n".join(json.dumps(e, indent=2)[:-2] for e in elements) + "\n}\n]"
    raw = gzip.compress(text.encode())
    chunks = [raw[i:i + 37] for i in range(0, len(raw), 37)]
    found = dict(iter_role_elements(chunks, {"810034882"}))
    assert list(found) == ["810034882"]
    assert found["810034882"]["rollegrupper"][0]["roller"][0]["person"]["navn"]["fornavn"] == "Morten"

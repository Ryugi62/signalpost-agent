"""Schema check over any produced envelope file (SIGNALPOST_ENVELOPES env var); skipped when absent."""
import json
import os
from pathlib import Path

import pytest

STATES = {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}
path = os.environ.get("SIGNALPOST_ENVELOPES") or str(Path(__file__).resolve().parents[1] / "reports/smoke-100/smoke-envelopes.jsonl")


@pytest.mark.skipif(not Path(path).exists(), reason="no envelope file")
def test_every_envelope_has_valid_external_claims():
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").split("\n") if line.strip()]
    orgs = [r["organisation_number"] for r in rows]
    assert len(orgs) == len(set(orgs))
    for row in rows:
        assert isinstance(row["organisation_number"], str) and len(row["organisation_number"]) == 9
        claims = row["profile"].get("external_claims")
        assert claims, row["organisation_number"]
        fields = {c["field"] for c in claims}
        assert {"official_website", "job_postings"} <= fields
        for claim in claims:
            assert claim["availability"] in STATES
            if claim["availability"] == "available":
                assert claim.get("source_url") and claim.get("retrieved_at")
                assert claim.get("value")

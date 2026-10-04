"""Refresh against the previous run: real changes reported, blocked/failed reads never reported as changes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from norway_company_agent.footprint.refresh_v2 import material_changes  # noqa: E402


def _p(employees=3, fin_status="available", records=None, site="https://foo.no/", jobs=()):
    claims = [{"field": "official_website", "availability": "available" if site else "not_available", "value": site}]
    claims += [{"field": "job_postings", "availability": "available", "source_url": u} for u in jobs] or [{"field": "job_postings", "availability": "not_available"}]
    return {"organisation_number": "123456785", "name": "FOO AS", "employees": employees,
            "evidence": {"registry": {"status": "available", "retrieved_at": "t"},
                         "financials": {"status": fin_status, "value": {"records": records} if records is not None else None}},
            "external_claims": claims}


def test_first_run_is_not_compared():
    assert material_changes(None, _p())["compared"] is False


def test_identical_rerun_has_no_changes():
    out = material_changes(_p(records=[1]), _p(records=[1]), previous_run_id="r1")
    assert out["compared"] and out["changes"] == [] and out["not_compared"] == []


def test_real_changes_are_reported():
    out = material_changes(_p(employees=3, site=None), _p(employees=5, jobs=("https://nav/1",)))
    fields = {c["field"] for c in out["changes"]}
    assert {"registry.employees", "external.official_website", "external.job_postings"} <= fields


def test_blocked_read_is_not_a_change():
    out = material_changes(_p(records=[1]), _p(fin_status="blocked", records=None))
    assert out["changes"] == [] and out["not_compared"] == ["financials.records"]


def test_runner_second_run_compares_and_preserves_previous(tmp_path, monkeypatch):
    import gzip
    import importlib.util
    import json
    import pytest

    root = Path(__file__).resolve().parents[1]
    bulk = tmp_path / "b.csv"
    with gzip.open(bulk, "wt", encoding="utf-8") as h:
        h.write('"organisasjonsnummer";"navn";"organisasjonsform.kode"\n"123456785";"FOO AS";"AS"\n')
    orgs = tmp_path / "orgs.jsonl"
    orgs.write_text('{"organisation_number":"123456785"}\n')
    profiles = tmp_path / "p.jsonl"

    def run(run_id):
        spec = importlib.util.spec_from_file_location("runner_refresh_" + run_id, root / "scripts" / "run_competition_batch.py")
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        monkeypatch.setattr(sys, "argv", ["x", "--organisations", str(orgs), "--bulk", str(bulk), "--output", str(tmp_path / "e.jsonl"),
                                          "--profiles-output", str(profiles), "--report", str(tmp_path / "r.json"),
                                          "--run-id", run_id, "--expected-count", "1", "--modules", "registry,accounting_obligation"])
        with pytest.raises(SystemExit):
            runner.main()

    run("r1")
    first = json.loads(profiles.read_text().splitlines()[0])
    assert first["refresh"]["compared"] is False and first["run_id"] == "r1"
    run("r2")
    second = json.loads(profiles.read_text().splitlines()[0])
    assert second["refresh"]["compared"] is True and second["refresh"]["previous_run_id"] == "r1" and second["refresh"]["changes"] == []
    archived = tmp_path / "p.before-r1.jsonl"
    assert archived.exists() and json.loads(archived.read_text().splitlines()[0])["run_id"] == "r1"

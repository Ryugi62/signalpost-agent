"""UC-5 hard global request budget (SPEC §6 AC-9..AC-12). Local HTTP server only; no internet."""
import http.server
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.budget import RequestBudget, plan_shares  # noqa: E402
from norway_company_agent.http_gate import RequestBudgetExhausted, charging, install_request_gate  # noqa: E402


def test_ac9_budget_never_grants_beyond_limit_under_threads():
    budget = RequestBudget(50)
    granted = []

    def worker():
        for _ in range(20):
            if budget.try_acquire("x"):
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 50
    snap = budget.snapshot()
    assert snap["spent"] == 50 and snap["remaining"] == 0
    assert snap["denied"] == 8 * 20 - 50


def test_ac9_category_ceiling_and_reserve():
    budget = RequestBudget(10, ceilings={"jobs": 3})
    assert all(budget.try_acquire("jobs") for _ in range(3))
    assert not budget.try_acquire("jobs")  # category ceiling
    assert budget.try_acquire("discovery")
    budget.reserve("jobs_details", 2)
    # 10 - 3 - 1 = 6 left, 2 reserved for jobs_details -> discovery can take 4 more
    assert sum(budget.try_acquire("discovery") for _ in range(10)) == 4
    assert budget.try_acquire("jobs_details") and budget.try_acquire("jobs_details")
    assert not budget.try_acquire("jobs_details")
    assert budget.snapshot()["spent"] == 10


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_ac10_gate_counts_every_request_including_redirect_hops(server):
    budget = RequestBudget(100)
    uninstall = install_request_gate(budget)
    try:
        with charging("website_registry"):
            urllib.request.urlopen(server + "/redirect", timeout=5).read()
        with charging("financials"):
            urllib.request.urlopen(server + "/ok", timeout=5).read()
    finally:
        uninstall()
    snap = budget.snapshot()
    assert snap["by_category"] == {"website_registry": 2, "financials": 1}
    # after uninstall, requests are no longer counted
    urllib.request.urlopen(server + "/ok", timeout=5).read()
    assert budget.snapshot()["spent"] == 3


def test_ac11_gate_refuses_request_beyond_limit_without_sending(server):
    budget = RequestBudget(2)
    uninstall = install_request_gate(budget)
    try:
        with charging("x"):
            urllib.request.urlopen(server + "/ok", timeout=5).read()
            urllib.request.urlopen(server + "/ok", timeout=5).read()
            with pytest.raises((RequestBudgetExhausted, urllib.error.URLError)) as info:
                urllib.request.urlopen(server + "/ok", timeout=5).read()
            if isinstance(info.value, urllib.error.URLError):
                assert isinstance(info.value.reason, RequestBudgetExhausted)
    finally:
        uninstall()
    snap = budget.snapshot()
    assert snap["spent"] == 2 and snap["denied"] == 1


def test_ac12_shares_fit_the_limit_for_1000_and_1100():
    for n in (100, 1000, 1100, 2000):
        shares = plan_shares(1950, n)
        assert sum(shares["ceilings"].values()) <= 1950
        assert shares["ceilings"]["registry_batch"] >= -(-n // 300)
        assert shares["ceilings"]["jobs"] >= 1


def test_ac16_refused_request_becomes_policy_block():
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner", ROOT / "scripts" / "run_competition_batch.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    from norway_company_agent.batch import evidence_terminal_state
    from norway_company_agent.http import FetchResult
    from norway_company_agent.official import fetch_official_modules

    records, _ = fetch_official_modules("810034882", {"financials"}, fetcher=lambda url: FetchResult(url, 0, 0, 0, error="request budget exhausted (not sent)"))
    profile = {"evidence": records}
    runner.mark_budget_refusals(profile)
    assert profile["evidence"]["financials"]["status"] == "blocked"
    assert evidence_terminal_state(profile["evidence"]["financials"]) == "blocked_policy"


def test_runner_end_to_end_offline(tmp_path, monkeypatch):
    """Whole runner path with network-free modules: one envelope per input and an exact request count of 0."""
    import gzip
    import importlib.util
    import json as _json

    bulk = tmp_path / "b.csv"
    with gzip.open(bulk, "wt", encoding="utf-8") as h:
        h.write('"organisasjonsnummer";"navn";"organisasjonsform.kode"\n"123456785";"FOO AS";"AS"\n')
    orgs = tmp_path / "orgs.jsonl"
    orgs.write_text('{"organisation_number":"123456785"}\n{"organisation_number":"987654321"}\n')
    spec = importlib.util.spec_from_file_location("runner2", ROOT / "scripts" / "run_competition_batch.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(sys, "argv", ["x", "--organisations", str(orgs), "--bulk", str(bulk), "--output", str(tmp_path / "e.jsonl"),
                                      "--profiles-output", str(tmp_path / "p.jsonl"), "--report", str(tmp_path / "r.json"),
                                      "--run-id", "t", "--expected-count", "2", "--modules", "registry,accounting_obligation"])
    with pytest.raises(SystemExit) as exit_info:
        runner.main()
    assert exit_info.value.code == 0
    report = _json.loads((tmp_path / "r.json").read_text())
    assert report["emitted_envelopes"] == 2 and report["validation"]["passed"]
    assert report["operations"]["requests"] == 0 and report["request_budget"]["limit"] == 1950


def test_exempt_categories_are_counted_but_not_limited():
    budget = RequestBudget(2, exempt={"financials"})
    assert all(budget.try_acquire("financials") for _ in range(5))
    assert budget.try_acquire("x") and budget.try_acquire("x") and not budget.try_acquire("x")
    snap = budget.snapshot()
    assert snap["spent"] == 2 and snap["spent_exempt"] == 5 and snap["total_outbound"] == 7


def test_plan_puts_recall_before_per_company_registry():
    plan = plan_shares(1950, 1000, registry_sites=100, group_candidates=60)
    assert plan["order"].index("website_discovery") < plan["order"].index("financials")
    assert plan["ceilings"]["website_registry"] == 500

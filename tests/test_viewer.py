"""Viewer built from v2 profiles: no starter LinkedIn leftovers, dated activity and profiles visible, scripts parse."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build(rows):
    spec = importlib.util.spec_from_file_location("viewer", ROOT / "scripts" / "build_prototype.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build(rows, None)


def test_viewer_shows_v2_layers_without_starter_leftovers(tmp_path):
    envelopes = (ROOT / "reports" / "smoke-100" / "smoke-envelopes.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line)["profile"] for line in envelopes[:20]]
    page = _build(rows)
    assert "exact LinkedIn profiles" not in page and 'data-mode="sentiment"' not in page
    assert "Dated posts on the company's own site" in page and "Company-owned profiles" in page and 'id="snapshot"' in page
    if shutil.which("node"):
        scripts = page.split("<script>")[1:]
        for index, chunk in enumerate(scripts):
            code = chunk.split("</script>")[0]
            path = tmp_path / f"s{index}.js"
            path.write_text("new Function(" + json.dumps(code) + ");", encoding="utf-8")
            assert subprocess.run(["node", str(path)], capture_output=True).returncode == 0

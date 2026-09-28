"""The repo passes its own safety check (generic rules plus any private
patterns configured on this machine or in CI)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_safety_check_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/safety_check.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_safety_check_catches_client_file(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import safety_check

    (ROOT / "zz_probe.sla").write_text("x")
    try:
        problems = safety_check.scan(["zz_probe.sla", "rules/brand/client.yaml"], [])
    finally:
        (ROOT / "zz_probe.sla").unlink()
    assert any("zz_probe.sla" in p for p in problems)
    assert any("client.yaml" in p for p in problems)

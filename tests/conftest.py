import os
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
os.environ["SLA_PREFLIGHT_RULES"] = str(HERE / "rules")
os.environ["SLA_PREFLIGHT_PROFILES"] = str(HERE / "profiles")

import make_fixtures  # noqa: E402

HAS_SCRIBUS = shutil.which("scribus") is not None
requires_scribus = pytest.mark.skipif(not HAS_SCRIBUS, reason="Scribus not installed")


@pytest.fixture(scope="session")
def fx(tmp_path_factory):
    """All synthetic fixtures: fx['sla'][name], fx['pdf'][name]."""
    return make_fixtures.build_all(tmp_path_factory.mktemp("fixtures"))


@pytest.fixture(scope="session")
def approved_render(fx, tmp_path_factory):
    """Approved render of the clean label, made with the engine's renderer."""
    from sla_preflight.scribus import render_png

    out = tmp_path_factory.mktemp("approved") / "good.png"
    return render_png(fx["sla"]["good"], out, dpi=150)

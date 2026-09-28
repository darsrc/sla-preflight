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


# Scribus PDF export settings: fontEmbedding 0 = embed, 1 = outline;
# outdst 0 = screen (RGB), 1 = printer (CMYK). Set every option explicitly:
# PDFfile() starts from the settings of the previous export.
SCRIBUS_EXPORTS = {
    "print_ready": dict(useDocBleeds=True, outdst=1, fontEmbedding=1),
    "no_bleed": dict(useDocBleeds=False, bleedt=0.0, bleedb=0.0, bleedl=0.0, bleedr=0.0,
                     outdst=1, fontEmbedding=1),
    "embedded_rgb": dict(useDocBleeds=True, outdst=0, fontEmbedding=0),
}


@pytest.fixture(scope="session")
def scribus_pdfs(fx, tmp_path_factory):
    """The clean label exported by real Scribus with different settings."""
    from sla_preflight.scribus import run_script

    out = tmp_path_factory.mktemp("scribus_pdf")
    lines = [f"scribus.openDoc({str(fx['sla']['good'])!r})"]
    for name, opts in SCRIBUS_EXPORTS.items():
        lines.append("p = scribus.PDFfile()")
        lines.append(f"p.file = {str(out / (name + '.pdf'))!r}")
        lines += [f"p.{k} = {v!r}" for k, v in opts.items()]
        lines.append("p.save()")
    lines.append("scribus.closeDoc()")
    run_script("\n".join(lines))
    return {name: out / f"{name}.pdf" for name in SCRIBUS_EXPORTS}

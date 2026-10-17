"""Real GTK/Qt -> ordered pikepdf merge -> API download; no renderer mocks."""

import io
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

import pikepdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app


@pytest.mark.parametrize(
    "executable,fixture", [("glabels-3-batch", "gtk"), ("glabels-batch-qt", "qt")]
)
def test_real_renderer_api_merge_download_and_restart(
    service_settings, monkeypatch, executable, fixture
):
    if not shutil.which(executable):
        pytest.skip(f"Real renderer unavailable: {executable}")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    cfg = service_settings
    cfg.GLABELS_EXECUTABLE = executable
    cfg.MAX_LABELS_PER_BATCH = 2
    cfg.MAX_INFLIGHT_JOBS = 1
    template = Path(__file__).parent / "fixtures" / f"{fixture}.glabels"
    document = template.read_text().replace(
        "</Objects>",
        '<Object-image src="asset.png" x="20pt" y="220pt" w="30pt" h="30pt" '
        'a0="1" a1="0" a2="0" a3="1" a4="0" a5="0"/></Objects>',
    )
    (cfg.TEMPLATES_DIR / "demo.glabels").write_text(document)
    Image.new("RGB", (16, 16), (255, 0, 0)).save(cfg.TEMPLATES_DIR / "asset.png")
    with TestClient(create_app(cfg)) as client:
        response = client.post(
            "/labels/print",
            json={
                "template_name": "demo.glabels",
                "data": [
                    {"ITEM": "A001 中文", "CODE": "A001"},
                    {"ITEM": "B002", "CODE": "B002"},
                    {"ITEM": "C003", "CODE": "C003"},
                ],
                "copies": 1,
            },
        )
        assert response.status_code == 202, response.text
        identifier = response.json()["job_id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = client.get(f"/labels/jobs/{identifier}").json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.03)
        assert job["status"] == "done", job
        response = client.get(job["download_url"])
        with pikepdf.open(io.BytesIO(response.content)) as pdf:
            assert len(pdf.pages) == 3
            assert all(len(list(page.get_images())) >= 1 for page in pdf.pages)
            assert all(
                [float(x) for x in p.MediaBox]
                == pytest.approx([0, 0, 612, 792], abs=0.001)
                for p in pdf.pages
            )
        final = cfg.OUTPUT_DIR / f"{identifier}.pdf"
        text = subprocess.run(
            ["pdftotext", "-layout", str(final), "-"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        pages = [p for p in text.split("\f") if p.strip()]
        assert len(pages) == 3
        assert all(
            code in page
            for code, page in zip(["A001", "B002", "C003"], pages, strict=True)
        )
        assert "中文" in unicodedata.normalize("NFKC", text)
        if shutil.which("zbarimg"):
            prefix = cfg.OUTPUT_DIR / "barcode-check"
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-singlefile",
                    "-r",
                    "150",
                    "-png",
                    str(final),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
            )
            barcode = subprocess.run(
                ["zbarimg", "--quiet", "--raw", str(prefix.with_suffix(".png"))],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            assert "A001" in barcode
            prefix.with_suffix(".png").unlink()
        original_expiry = job["expires_at"]
    assert list(cfg.TEMP_DIR.iterdir()) == []
    with TestClient(create_app(cfg)) as client:
        after = client.get(f"/labels/jobs/{identifier}").json()
        assert after["expires_at"] == original_expiry
        assert client.get(after["download_url"]).content == response.content

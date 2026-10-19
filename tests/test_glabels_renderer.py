import asyncio
import sys

import pytest

from app.utils.glabels_renderer import (
    GlabelsRenderer,
    GlabelsRunError,
    GlabelsTimeoutError,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_segment", [False, True])
async def test_native_process_argv_and_bounded_diagnostics(
    tmp_path, monkeypatch, parent_segment
):
    if parent_segment:
        # Exercise path normalization even when Windows short names are absent.
        nested = tmp_path / "nested"
        nested.mkdir()
        tmp_path = nested / ".."
    template, data, output = [
        tmp_path / n for n in ("with spaces.glabels", "data.csv", "out.pdf")
    ]
    template.write_text("opaque")
    data.write_text("ITEM\nA")
    original = asyncio.create_subprocess_exec
    observed = []

    async def spawn(*argv, **kwargs):
        observed.append((argv, kwargs))
        return await original(
            sys.executable,
            "-c",
            "import sys;sys.stderr.write('x'*100000);sys.exit(3)",
            **kwargs,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    renderer = GlabelsRenderer(glabels_bin=sys.executable)
    with pytest.raises(GlabelsRunError) as error:
        await renderer.run_batch(
            template_path=template, csv_path=data, output_pdf=output
        )
    assert len(str(error.value)) < 4200
    assert observed[0][0] == (
        sys.executable,
        "-o",
        str(output.resolve()),
        "-i",
        str(data.resolve()),
        "--copies=1",
        str(template.resolve()),
    )
    assert observed[0][1]["cwd"] == template.resolve().parent


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancellation_reap_actual_child(
    tmp_path, monkeypatch, cancel
):
    template, data = tmp_path / "demo.glabels", tmp_path / "data.csv"
    template.write_text("opaque")
    data.write_text("ITEM\nA")
    original = asyncio.create_subprocess_exec
    children = []

    async def spawn(*argv, **kwargs):
        # Keep taskkill itself functional on Windows.
        if argv[0] == "taskkill.exe":
            return await original(*argv, **kwargs)
        child = await original(
            sys.executable, "-c", "import time;time.sleep(60)", **kwargs
        )
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    renderer = GlabelsRenderer(
        glabels_bin=sys.executable, default_timeout=10 if cancel else 0.2
    )
    task = asyncio.create_task(
        renderer.run_batch(
            template_path=template, csv_path=data, output_pdf=tmp_path / "out.pdf"
        )
    )
    if cancel:
        while not children:
            await asyncio.sleep(0.01)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else GlabelsTimeoutError):
        await task
    assert children[0].returncode is not None

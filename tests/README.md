# Tests

Use Python 3.14 (the tested runtime) and uv 0.12.10. Install uv if needed with
`python -m pip install uv==0.12.10`, then sync the committed lockfile:

```sh
uv sync --locked
uv run --locked python -m pytest
uv run --locked python -m ruff check app tests
uv run --locked python -m ruff format --check app tests
uv run --locked python -m mypy app
uv run --locked python -m bandit -c pyproject.toml -r app
uv pip check
```

Tests cover shared weighted capacity/reserve/fairness, cancelled leases, real
spawn-worker timeout/crash/reap/recovery, native renderer process cleanup,
CSV/scalar/path contracts, SQLite ownership/constraints/expiry, restart
reconciliation, bounded admission, download/cleanup ownership and API/SSE.
The temporary paths and service settings are isolated from deployment data.

`test_integration.py` calls real GTK/Qt binaries through the entire API pipeline:
named CSV, CJK, multiple render batches, ordered pikepdf merge, page geometry,
barcode decoding, download and restart under the same ID. It skips a renderer
explicitly if unavailable on the host.

Eight additional real-renderer cases compare complete jobs with page-aligned
batches for both copy orders and copies=1/2, on a three-slot-per-page fixture.
They check each page's label sequence, including partial final pages. Unit/API
tests reject missing or oversized page declarations, fail publication on PDF
page-count mismatch, and preserve completed downloads after restart.

Container tests supply those binaries:

```sh
docker build --target test -t labels-test .
docker run --rm --cpus 4 --memory 2g labels-test
docker build --target qt-test -t labels-qt-test .
docker run --rm --cpus 4 --memory 2g labels-qt-test
```

The default production build excludes test dependencies. Test stage includes
tests/fixtures and Poppler/zbar; qt-test additionally compiles the fixed upstream
revision from Dockerfile. Fixtures are authored here, without parsing production
templates. `fixtures/gtk.glabels` and `fixtures/qt.glabels` are renderer-specific
test documents, not production templates. Both use the `.glabels` extension but
have different content. Tests copy the selected fixture to `demo.glabels` in an
isolated template directory; no demo template is installed by the runtime image.
A Windows host without symlink permission skips the symlink test;
Linux container tests exercise it.

Short tests/accelerated retention cycles do not establish a production capacity
SLA or substitute for longer workload and printer acceptance testing. Coverage
of spawn-child PDF operations is supplemented by direct worker behavior tests;
parent-only coverage is not a claim that native code was untested.

Quality regression tests also verify app-specific deployment limits and rate counters,
log severity floors and sink failures, OpenAPI media/error contracts, and execution
failures that must retain resource accounting.

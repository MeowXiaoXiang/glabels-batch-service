# Tests

Use Python 3.14.9 (selected by `.python-version`) and uv 0.13.5. Update uv with
its existing installation method; for a pip-managed copy, use
`python -m pip install --upgrade uv==0.13.5`, then sync the committed lockfile:

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
A separate [test_data](../test_data/README.md) directory holds older manual GTK
examples; the automated tests do not use them.
A Windows host without symlink permission skips the symlink test;
Linux container tests exercise it.

Pytest prints statement coverage and missing lines. To save a report, run
`uv run --locked python -m pytest --cov-report=xml`; `coverage.xml` is generated
and should not be committed. Branch coverage is not enabled. Worker behavior is
tested in real spawned processes, whose executed lines may not appear in the
parent's coverage report. A low percentage in `pdf_worker.py` alone does not
mean merging went untested.
CI requires at least 80% statement coverage for each full suite. Targeted test
runs can use `--no-cov`; do not use their partial totals as full-suite coverage.

CI audits the locked Linux runtime dependencies and the full dependency export
(including dev tools) on Linux and Windows. A weekly scheduled audit checks the
full export on both platforms without renderer builds; scheduled workflows run
from the default branch. Manual workflow dispatch runs the complete CI pipeline.
CI also submits a real HTTP
job, downloads its PDF and checks graceful stop in the production image.
`runtime_smoke.py` uses only the standard library against a running service;
CI supplies `fixtures/gtk.glabels` as its demo template. See the exact commands in
[ci.yml](../.github/workflows/ci.yml). These checks do not establish a production
capacity guarantee or replace acceptance with actual templates and printers.

Quality regression tests also verify app-specific deployment limits and rate counters,
log severity floors and sink failures, OpenAPI media/error contracts, and execution
failures that must retain resource accounting.

Regression tests exercise repeated cold spawn and external worker kills,
continuous mixed scheduler producers with cancellation, transient/persistent
SQLite write failures, and fatal shutdown through a separate server process.
`fixtures/failing_server.py` installs fault injection only in that subprocess;
it is never part of the runtime image. Actual OOM recovery is not exercised by CI.

TestClient uses the locked `httpx2` development dependency. Keep that backend
consistent across Windows and renderer-container tests; plain `httpx` is not
needed by this project.

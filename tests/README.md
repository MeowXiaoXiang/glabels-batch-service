# Tests

Use Python 3.14+ and `python -m pip install -r requirements-dev.txt`.

```sh
python -m pytest
python -m ruff check app tests
python -m ruff format --check app tests
python -m mypy app
python -m bandit -c pyproject.toml -r app
python -m pip check
```

Tests cover shared weighted capacity/reserve/fairness, cancelled leases, real
spawn-worker timeout/crash/reap/recovery, native renderer process cleanup,
CSV/scalar/path contracts, SQLite ownership/constraints/expiry, restart
reconciliation, bounded admission, download/cleanup ownership and API/SSE.
The temporary paths and service settings are isolated from deployment data.

`test_integration.py` calls real GTK/Qt binaries through the entire API pipeline:
named CSV, CJK, multiple render batches, ordered pikepdf merge, page geometry,
barcode decoding, download and restart under the same ID. It skips a renderer
explicitly if unavailable on the host. Container tests supply those binaries:

```sh
docker build --target test -t labels-test .
docker run --rm --cpus 4 --memory 2g labels-test
docker build --target qt-test -t labels-qt-test .
docker run --rm --cpus 4 --memory 2g labels-qt-test
```

The default production build excludes test dependencies. Test stage includes
tests/fixtures and Poppler/zbar; qt-test additionally compiles the fixed upstream
revision from Dockerfile. Fixtures are authored here, without parsing production
templates. A Windows host without symlink permission skips the symlink test;
Linux container tests exercise it.

Short tests/accelerated retention cycles do not establish a production capacity
SLA or substitute for longer workload and printer acceptance testing. Coverage
of spawn-child PDF operations is supplemented by direct worker behavior tests;
parent-only coverage is not a claim that native code was untested.

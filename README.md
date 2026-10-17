# gLabels Batch Service

An asynchronous label PDF service for GTK gLabels and Qt gLabels. One submission
produces one final PDF; internal CSVs and batch PDFs are temporary.

[繁體中文](README_tw.md)

## Run

Requires Python 3.14 or newer and a working gLabels batch executable. The default
Docker runtime includes GTK, fonts, and the Python dependencies:

```sh
cp .env.example .env
# Put your own templates in templates/, configured for named, header-row CSV.
docker compose up --build -d
curl http://localhost:8000/ready
```

Keep both `state/` and `output/` persistent. Compose mounts them automatically.
Run one service instance and one Uvicorn worker per store. A second owner of the
same SQLite store is rejected. SQLite is a local result index, not a distributed
queue. The default Compose limits are 4 CPUs and 2 GB memory.

For an installed local renderer:

```sh
python -m pip install -r requirements.txt
python -m app.main
```

Interactive documentation: `/docs`. `/health` is liveness; `/ready` indicates
whether the coordinator can accept work. Oversized bodies return 413; invalid
inputs return 422; a full queue or unavailable coordinator returns 503 with
`Retry-After`. The request limit applies before JSON parsing, including chunked
bodies.

Body admission concurrency is bounded before JSON parsing by the pending plus
inflight capacity. The provided Uvicorn entrypoints also cap concurrent
connections at 128.

## GTK / Qt

Set `GLABELS_EXECUTABLE` to an executable name or path and restart:

```dotenv
GLABELS_EXECUTABLE=glabels-3-batch
# GLABELS_EXECUTABLE=/opt/glabels/bin/glabels-batch-qt
# GLABELS_EXECUTABLE=/opt/service/bin/glabels-wrapper
```

The same adapter passes `-o`, `-i`, `--copies`, and the template path as separate
arguments. Shell command strings are not supported. A compatible wrapper must
forward arguments, exit codes and signals, and own its children. Install the Qt
runtime, fonts and platform support first; changing a path does not install them.
For a headless Qt deployment, provide a supported platform configuration such as
`QT_QPA_PLATFORM=offscreen`, or a suitable wrapper. GTK remains the default image;
the optional `qt-test` build target compiles a fixed Qt source revision for tests.

Templates must be compatible with the selected renderer. The service does not
parse, convert, or infer template fields. Catalog endpoints return names only.
Ensure your template uses the service's named CSV contract. See
[templates/README.md](templates/README.md).

Copies use each renderer's native semantics **per batch**. GTK and Qt can order
copies differently. Each batch starts a new page; merging concatenates pages and
does not fill an earlier batch's unused label positions. Supply continuous serial
numbers in the data rather than relying on template variables across CLI runs.

## API

```sh
curl -X POST http://localhost:8000/labels/print \
  -H 'Content-Type: application/json' \
  -d '{"template_name":"demo.glabels","data":[{"ITEM":"A001","CODE":"123"}],"copies":1}'
```

Successful admission returns HTTP 202:

```json
{"job_id":"123e4567-e89b-42d3-a456-426614174000","status":"pending"}
```

| Endpoint | Purpose |
|---|---|
| `POST /labels/print` | Submit a job |
| `GET /labels/jobs/{job_id}` | Status, progress, expiry, error, download URL |
| `GET /labels/jobs/{job_id}/stream` | SSE using the same status schema |
| `GET /labels/jobs/{job_id}/download` | Download a completed PDF; `?preview=true` displays inline |
| `GET /labels/jobs?limit=10` | Recent, unexpired jobs; limit 1–100 |
| `GET /labels/templates` | Available template names |
| `GET /labels/templates/{name}` | Check a template name exists |
| `GET /metrics` | Prometheus metrics, when enabled |

Status is `pending → rendering → merging → done`, or `failed`. Single-batch jobs
can skip `merging`, while still validating their PDF in the isolated worker.
Progress reports rendered batches; completing all render batches does not mean
the final PDF is ready. Internal batches have indexes, not public child job IDs.
Disconnecting a polling/SSE client does not cancel an accepted job.

Records contain scalar values only. CSV columns follow first appearance across
the whole request, remain consistent across batches, and always include a header.
Missing/null values become empty cells, booleans `true`/`false`; quoting and
newlines use standard UTF-8 CSV. Nested values, NUL and nonfinite numbers are
rejected. The template provider owns field mapping and layout correctness.

## Results and restart

SQLite stores minimal metadata; final PDFs remain in `output/<job_id>.pdf`.
The main process publishes a validated file by rename, then marks the job done.
Only final PDFs are downloadable. CSVs, batch PDFs and staging files are cleaned
after their actual operations end.

Completed results remain available under their original job ID after a normal
service/container restart, until their recorded expiry (24 hours by default).
Restarting, downloading again or changing retention does not extend that expiry.
Startup reconciles a published final whose completion transaction was interrupted.
Other unfinished jobs become `failed` with `interrupted`; no automatic resume,
retry, request deduplication or durable input-payload storage is provided.

Expired/unknown jobs return 404. An unexpired completed job with a missing final
returns 410; unfinished downloads return 409. Cleanup coordinates open downloads,
deletes the artifact before its index row, and retries failed deletions. Failed
job records also expire. Only files belonging to indexed jobs are cleaned; legacy
PDFs from older releases are not automatically imported or deleted.

## Capacity and lifecycle

Render and merge share a static weighted budget. CPU quota, affinity and process
CPU count determine the cap; `API_CPU_RESERVE` defaults to 1. `WORK_TOKENS=0` uses
automatic sizing, while a positive value further caps it. Render costs 1; merge
defaults to 2 and clamps to the available budget. Weights estimate admission
cost, not CPU affinity or hard OS resource isolation.

Merge finishing reserve prevents new renders taking all capacity. Render batches
rotate among jobs; low-capacity configurations allow a render between consecutive
merges. One warm spawn worker handles merge/validation, with pending work held by
the shared scheduler. Crash/timeout recovery confirms actual process exit before
releasing the lease or deleting its workspace. An unconfirmed exit makes the
coordinator unavailable for a controlled restart.

Configuration bounds queued/inflight jobs, request size, records×copies, batches,
PDF size/pages, workspace size and disk headroom. Workspace/disk checks run at
operation boundaries and periodically during rendering; container limits remain
necessary for hard resource bounds. Deploy under a supervisor that also owns
children (the provided single-process container does this). Linux renderer trees
use dedicated process groups; Windows uses native child-tree termination.

`SIGTERM` drains accepted work within the configured budget, then stops and reaps
remaining children. Compose allows 60 seconds, including Uvicorn's 5-second HTTP
grace period and the application's drain/reap budgets. Persistence covers normal
restart; power-loss durability of the filesystem/volume requires separate testing.

## Development

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check app tests
python -m ruff format --check app tests
python -m mypy app
python -m bandit -c pyproject.toml -r app
python -m pip check
docker build --target test -t labels-test .
docker run --rm --cpus 4 --memory 2g labels-test
docker build --target qt-test -t labels-qt-test .
docker run --rm --cpus 4 --memory 2g labels-qt-test
```

Real renderer tests skip explicitly when that executable is unavailable on the
host; GTK/Qt container stages provide the corresponding binaries. See
[tests/README.md](tests/README.md). The runtime image does not include research,
tests, Qt build tools, pypdf, qpdf CLI or template XML parsers.

The Docker base image is pinned by digest. `constraints-linux.txt` records the
validated Python 3.14/Linux amd64 runtime resolution and is used during Docker
installs; refresh it deliberately when upgrading dependencies. It is a version
constraint set, not a hash lock or a Windows environment export.

Version 3 changes the API and environment configuration directly: `running`,
template introspection fields, `MAX_PARALLEL` and `KEEP_CSV` are removed. Replace
old deployment settings using `.env.example`; no compatibility layer is provided.

# gLabels Batch Service

An asynchronous label PDF service for GTK gLabels and Qt gLabels. One submission
produces one final PDF; internal CSVs and batch PDFs are temporary.

[繁體中文](README_tw.md)

Contribution and commit message guidelines: [CONTRIBUTING.md](CONTRIBUTING.md).

## Run

The default Docker runtime includes Python, GTK, fonts, and the Python
dependencies. The host only needs Docker with Compose:

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

To run without Docker, use Python 3.14 or newer and install a working gLabels
batch executable, its native libraries, and fonts:

```sh
uv sync --locked --no-dev
uv run --locked --no-dev python -m app.main
```

Local commands use uv 0.12.10; install that version if needed with
`python -m pip install uv==0.12.10`. Docker includes the installation step and
does not require uv on the host. Python 3.14 is the tested runtime; uv uses a
project-local `.venv` without changing your system Python packages.

Interactive documentation: `/docs`. `/health` is liveness; `/ready` indicates
whether the coordinator can accept work. Oversized bodies return 413; invalid
inputs return 422; a full queue or unavailable coordinator returns 503 with
`Retry-After`. The request limit applies before JSON parsing, including chunked
bodies.

Body admission concurrency is bounded before JSON parsing by the pending plus
inflight capacity. The provided Uvicorn entrypoints also cap concurrent
connections at 128.

## GTK / Qt

Each service instance uses **one renderer**, selected globally at deployment.
API requests do not select GTK/Qt, and a job never mixes renderers.

Current Docker targets:

| Build target | Installed renderers | Default command |
|---|---|---|
| `production` (default, including Compose) | GTK | API server |
| `test` | GTK | pytest |
| `qt-test` | GTK and Qt | pytest |

The two renderers in `qt-test` are for compatibility testing. A dedicated Qt
production target is not provided yet. The default GTK image cannot run Qt just
by changing an environment variable; deploy the matching runtime first.

Set `GLABELS_EXECUTABLE` to an executable name or path and restart:

```dotenv
GLABELS_EXECUTABLE=glabels-3-batch
# GLABELS_EXECUTABLE=/opt/glabels/bin/glabels-batch-qt
# GLABELS_EXECUTABLE=/opt/service/bin/glabels-wrapper
```

The same adapter passes `-o`, `-i`, `--copies=1`, and the template path as separate
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

The service owns copies and their order. `copy_order="sets"` (default) repeats
the complete input: `ABCD`, copies=2 → `ABCDABCD`. `"per_record"` repeats each
record: `AABBCCDD`. The renderer always receives copies=1. CSV rows are generated
from a virtual sequence per admitted render batch; copies are not materialized
as a second expanded list in memory. Sets continue into available page slots;
each set does not automatically start a new page.

When the effective label count exceeds `MAX_LABELS_PER_BATCH`, the request must
declare `labels_per_page` for its template. Intermediate batches contain whole
pages, rounded down within that limit; the final batch may be partial. Missing
declarations, a page larger than the batch limit, and excessive batch/page counts
return HTTP 422 before creating a job. A single render does not require this
declaration. A declared page count is checked against each batch PDF by the
isolated merge worker; a mismatch fails the job without publishing a final.

The template provider must verify the declared page capacity, the first-slot
start, and continuous filling without native grouping. The service cannot infer
these from an opaque template or prove slot geometry from PDF page counts alone.
Supply business serial numbers and any copy/page-specific values as data. Native
template copy variables now see copies=1, and native page/sequence variables reset
per invocation. Templates relying on those variables need adaptation and layout
acceptance with the chosen renderer; arbitrary templates are not automatically
equivalent to one monolithic render.

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

### Using copies and copy_order

`copies` determines how many labels each record produces; `copy_order` determines
their sequence. Both are JSON fields on each `POST /labels/print`, with no extra
Qt flags or environment variables required.

For example, assume your deployed `demo.glabels` uses the `ITEM` field and has
four label positions per page:

```json
{
  "template_name": "demo.glabels",
  "data": [{"ITEM": "A"}, {"ITEM": "B"}, {"ITEM": "C"}],
  "copies": 2,
  "copy_order": "sets",
  "labels_per_page": 4
}
```

| copy_order | Meaning | Label sequence | Pages in this example |
|---|---|---|---|
| `sets` (default) | Repeat the complete input in order | `ABCABC` | `ABCA` then `BC` |
| `per_record` | Repeat each record consecutively | `AABBCC` | `AABB` then `CC` |

Change only `copy_order` to `"per_record"` to select the second ordering. Omitting
it selects `sets`; omitting `copies` selects one copy, where both orders are the
same. Sets do not force a page break between copies. Both examples produce six
labels in one two-page PDF, not two PDF files.

Use your actual template's capacity for `labels_per_page`, not the example's
four. This declaration aligns service batches; it does not change the template's
layout. It is required when the job needs batching.

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

Request options: `copies` defaults to 1; `copy_order` is `sets` or `per_record`;
`labels_per_page` is a positive integer or null. Status/SSE retain these options
after restart.

## Results and restart

SQLite stores minimal metadata; final PDFs remain in `output/<job_id>.pdf`.
Schema v1 includes copy ordering and page declarations. Unsupported schema
versions are rejected at startup.
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
uv sync --locked
uv run --locked python -m pytest
uv run --locked python -m ruff check app tests
uv run --locked python -m ruff format --check app tests
uv run --locked python -m mypy app
uv run --locked python -m bandit -c pyproject.toml -r app
uv pip check
docker build --target test -t labels-test .
docker run --rm --cpus 4 --memory 2g labels-test
docker build --target qt-test -t labels-qt-test .
docker run --rm --cpus 4 --memory 2g labels-qt-test
```

Real renderer tests skip explicitly when that executable is unavailable on the
host; GTK/Qt container stages provide the corresponding binaries. See
[tests/README.md](tests/README.md). The runtime image does not include research,
tests, Qt build tools or qpdf CLI. The service does not parse template contents.

`pyproject.toml` declares runtime dependencies, the `dev` dependency group, and
tool settings. Commit the generated `uv.lock` with dependency changes; it locks
transitive versions and artifact hashes for Windows and Linux. CI and Docker use
`--locked` and fail when the declarations and lockfile disagree. Production
installs exclude the dev group and launch Uvicorn directly; uv is only mounted
during installation. The Python and uv build images are pinned by digest.
See [CONTRIBUTING.md](CONTRIBUTING.md) for dependency updates. gLabels, Qt/GTK,
fonts, and other OS packages are managed by the deployment, separately from uv;
the default Docker image installs the GTK stack.

Version 3 changes the API and environment configuration directly: `running`,
template introspection fields, `MAX_PARALLEL` and `KEEP_CSV` are removed. Replace
old deployment settings using `.env.example`; no compatibility layer is provided.

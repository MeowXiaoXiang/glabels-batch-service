# Agent guide — glabels-batch-service

Read [README.md](../README.md), [CONTRIBUTING.md](../CONTRIBUTING.md), and
[tests/README.md](../tests/README.md) for the supported behavior, dependency
workflow, validation, and commit convention. A local commit does not authorize
a push.

## Environment and dependencies

- Use the existing local tools; Windows uses PowerShell. Docker provides the
  GTK/Qt renderer test environments.
- Use uv 0.12.10 and the committed `uv.lock`. `pyproject.toml` contains runtime
  dependencies, the `dev` dependency group, and tool settings. Do not create a
  parallel requirements or constraints file.
- Run `uv sync --locked`, then `uv run --locked python -m pytest`, Ruff check and
  format checks, Mypy, Bandit, and `uv pip check`. Follow the CI workflow for the
  exported-lock runtime audit and container checks.
- Host renderer tests skip explicitly if a binary is unavailable. Use fresh
  `test` and `qt-test` Docker targets to exercise real GTK and Qt respectively.
- Keep the version in `app/__init__.py` synchronized with `pyproject.toml`.

## Architecture

- `JobManager` owns admission and lifecycle; `job_pipeline.py` dispatches render
  and merge work through the shared weighted CPU budget.
- `job_store.py` persists minimal job metadata in SQLite. One instance and one
  Uvicorn worker own a store. Completed IDs and downloads survive normal restart
  until their original expiry; unfinished work is interrupted, not resumed.
- `label_print.py` generates named-header CSV batches lazily. Copies and
  `copy_order` are service-owned; every renderer invocation receives copies=1.
  Multi-batch requests must declare `labels_per_page` for page alignment.
- `glabels_engine.py` invokes the configured executable through argv without a
  shell. One instance selects one GTK/Qt renderer or compatible wrapper.
- `pdf_merger.py` manages isolated spawn workers; `pdf_worker.py` opens paths,
  checks page counts, merges with pikepdf, and saves. Do not import native PDF
  operations into the event loop or release leases before children are reaped.
- Templates are opaque. `template_service.py` checks safe names and discovers
  files; the renderer alone understands template content. Do not restore XML
  parsing, format detection, or field introspection.
- States are `pending → rendering → merging → done`, or `failed`. A single batch
  can skip the merging state but still undergoes isolated PDF validation.
- `output/<job_id>.pdf` is the only downloadable artifact. Temporary CSV/batch
  PDFs are cleaned after actual operations stop. Keep state/output persistent.

## Changes and verification

- Keep request/status models, API examples, both READMEs, and configuration
  examples consistent when changing supported behavior.
- Preserve bounded admission, process-tree cleanup, SQLite ownership,
  publication/restart reconciliation, and download/expiry coordination.
- Schema changes must preserve retained results through a transactional
  migration and have behavior tests.
- Configuration lives in `app/config.py`; use `.env.example` as the operator
  reference. Avoid copying defaults into another table that can become stale.
- Production Docker contains GTK and runtime Python dependencies. `qt-test`
  includes both renderers for tests; changing an executable path does not
  install the required Qt runtime, templates, fonts, or platform support.

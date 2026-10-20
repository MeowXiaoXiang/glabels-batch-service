# Contributing

Repository guidance for coding agents lives in [AGENTS.md](AGENTS.md).

## Dependencies and local environment

Use Python 3.14 and uv 0.12.10, the version required by `pyproject.toml` and used
by CI and Docker. If uv is not installed, run
`python -m pip install uv==0.12.10`. From the repository root:

```sh
uv sync --locked
uv run --locked python -m pytest
uv pip check
```

uv creates the project's `.venv`; do not commit it or share it with another
project. Runtime dependencies belong in `[project].dependencies`; development
tools belong in `[dependency-groups].dev`. Keep tool settings in the same
`pyproject.toml`. Commit `uv.lock` with every dependency change and let uv update
it; do not edit it manually or maintain parallel requirements/constraints files.

Use explicit versions when adding or upgrading a direct dependency:

```sh
uv add 'pikepdf==10.16.0'
uv add --dev 'pytest==9.1.1'
```

Replace those versions with the intended upgrade. To update a transitive
dependency within the declared constraints, use
`uv lock --upgrade-package PACKAGE`. Review the lockfile diff. Run
`uv sync --locked` and complete the checks in [tests/README.md](tests/README.md), including
the affected renderer container tests. Review uv upgrades separately and update
the required version, CI installer, Docker image digest, and documentation
together. `--locked` must remain enabled in CI and Docker builds.

Production installs use `uv sync --locked --no-dev`; a local production launch
through uv also needs `uv run --locked --no-dev ...` to keep development tools
excluded. Docker launches the installed Uvicorn directly. Renderer executables,
Qt/GTK libraries, and fonts are managed by the deployment rather than uv.

CI exports a temporary runtime requirements file from the lockfile for
`pip-audit`. Such exports are generated integration artifacts, not another
dependency source to commit. The lockfile records versions and artifact hashes;
periodic dependency review is still needed for security updates.

## Commit messages

Use English subjects and bodies for new commits.

```text
type(scope): short description

- Describe a concrete change and why it is needed.
- Describe another related change or a material compatibility limit.
- State the relevant validation and its result.
```

The type describes the kind of change; the optional scope names the affected
area, such as `pipeline`, `store`, `api`, or `docker`. Omit the scope when it does
not help. Keep the subject concise, use an imperative verb, and omit a trailing
period. For a substantial change, include a body with `-` bullet points separated
from the subject by one blank line. A small, self-explanatory change may use only
a subject. Write actual newlines, not literal `\n` sequences.

| Type | Use |
|---|---|
| `feat` | Add or change a supported capability |
| `fix` | Correct unintended behavior |
| `refactor` | Restructure code without changing supported behavior |
| `perf` | Improve performance; explain the evidence |
| `docs` | Change documentation |
| `test` | Change tests without a related implementation change |
| `ci` | Change CI workflows |
| `build` | Change dependencies, packaging, or build configuration |
| `chore` | Other repository maintenance |

Choose the type for the main outcome. A feature commit may include the code,
tests, configuration, migration, and documentation needed to make it complete;
do not split those solely by file type. Split independent work into separate
commits that are coherent and reviewable on their own. Bodies should explain the
final behavior, not recount the conversation or every editing step. Report only
validation actually performed, including meaningful skips or limitations.

For incompatible API or supported-behavior changes, add `!` before the colon and
a `BREAKING CHANGE:` footer after the bullet list. State what callers or operators
must change. For example:

```text
feat(pipeline)!: normalize copy ordering and align render batches

- Generate copy sequences per batch without materializing an expanded list.
- Align intermediate batches to the caller's declared page capacity.
- Verify both renderers against complete-job output.

BREAKING CHANGE: Requests that need batching must declare labels_per_page.
```

This convention applies to new commits; existing history does not need to be
rewritten to match it.

## Publishing commits

Creating a local commit and pushing it are separate steps. Keep commits local
until the changes have been discussed and the maintainer explicitly requests a
push. A request to check or commit changes does not authorize publishing them.

# Contributing

## Commit messages

Use English subjects and bodies, following the prevailing project history.

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

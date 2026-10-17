# Template contract

Put deployment-provided `.glabels` files here. The service lists safe basenames
and verifies existence/path boundaries; only the configured gLabels renderer
opens and interprets them. A template must be compatible with that renderer.

Configure templates for UTF-8 comma-separated data with **named fields from the
first header row**. JSON keys become CSV column names in first-appearance order
across the complete request. Null/missing values are empty; booleans use
`true`/`false`; quotes/newlines are escaped by Python's CSV writer. The service
does not infer header modes, validate template field semantics or convert files.

The renderer runs with the template directory as its working directory, with
absolute CSV/output paths. Relative assets can be deployed alongside templates.
Only `.glabels` basenames are catalogued; symlinks escaping this directory and
API path traversal are rejected.

Keep templates/assets unchanged while jobs are running. Drain before updating a
template bundle; completed PDFs are retained independently, but active jobs do not
snapshot or version the deployment's template and asset directory.

Each render batch starts a new page. Copies and template variables use native
renderer behavior per invocation. Supply continuous identifiers in the data.
Keep fonts/assets available in the deployed runtime and verify printed layout
and barcode readability with your actual template/printer.

The authored GTK/Qt fixtures in `tests/fixtures` demonstrate the service CSV
contract; they do not imply arbitrary GTK and Qt templates are interchangeable.

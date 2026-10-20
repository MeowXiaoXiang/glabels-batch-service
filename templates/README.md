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
Only `.glabels` basenames are catalogued; template symlinks escaping this
directory and API path traversal are rejected. Asset paths inside templates are
interpreted by the renderer, not checked by this catalog.

Keep templates/assets unchanged while jobs are running. Drain before updating a
template bundle; completed PDFs are retained independently, but active jobs do not
snapshot or version the deployment's template and asset directory.

The service expands `copies` in its own virtual input sequence and always invokes
the renderer with copies=1. `copy_order="sets"` repeats the whole input;
`"per_record"` repeats each record. Native copy variables therefore do not track
the public request's copies. Supply continuous identifiers and any business
copy/page-specific values in the data; native variables reset per invocation.

Jobs that need batching must supply the trusted `labels_per_page` of the chosen
template. Batches are aligned to whole pages within the work limit; only the
final page may have unused slots. Templates/wrappers must start at the first slot
and fill continuously without native per-group page breaks. Page-count mismatch
fails the job before publication, but matching page counts do not certify slot
geometry or field semantics. The service never reads layout metadata from the
template. Verify this declaration and the output with your real template.
Keep fonts/assets available in the deployed runtime and verify printed layout
and barcode readability with your actual template/printer.

The GTK/Qt fixtures in `tests/fixtures` demonstrate the service CSV contract;
GTK and Qt templates are not interchangeable just because they share a file
extension. [test_data](../test_data/README.md) contains separate manual GTK
examples, including a historical headerless example that does not match the
current API's CSV contract.

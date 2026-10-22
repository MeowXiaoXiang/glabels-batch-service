# Manual GTK examples

These older examples are kept for manual testing in GTK gLabels. Automated
tests use `tests/fixtures` instead, and the Docker build excludes `test_data`.

| Files | CSV mode | Use with this service |
|---|---|---|
| `demo.glabels`, `test.csv` | First row names the `ITEM` and `CODE` fields | Named-field example; copy the template into the deployed template directory |
| `non_head_demo.glabels`, `non_head_test.csv` | No header; fields addressed as `1` and `2` | Historical standalone example; adapt the template to named fields before API use |

Both templates contain saved CSV paths under `/test/`. When opening them in the
editor, select the corresponding local CSV file. The service passes its own CSV
path to the renderer with `-i`; API requests contain JSON records, not CSV files.

The service always writes a header, so sending data to the headerless template
unchanged will not match its expected input. Keep this pair as a standalone
example rather than disabling the service's header.

Check page capacity, fonts and output before using either template in a
deployment. These GTK files are separate from the Qt fixture; see the
[template contract](../templates/README.md).

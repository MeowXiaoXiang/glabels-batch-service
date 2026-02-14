# Templates Directory

Place your **gLabels template files** (.glabels) here for the label printing service.

## Quick Start

1. **Add your template file:**

   ```text
   templates/
   └── your_template.glabels
   ```

2. **Use in API:**

   ```json
   {
     "template_name": "your_template.glabels",
     "data": [
       {"FIELD1": "Value1", "FIELD2": "Value2"}
     ]
   }
   ```

## Requirements

- **Field mapping**: JSON keys must match template field names exactly (case-sensitive)
- **File format**: .glabels extension required
- **Encoding**: Use UTF-8 for non-ASCII characters (Chinese, etc.)
- **Testing**: Verify template in gLabels desktop app before uploading

## Example

If your template defines fields `CODE` and `ITEM`:

```json
{
  "template_name": "demo.glabels",
  "data": [
    {"CODE": "A001", "ITEM": "Product A"},
    {"CODE": "A002", "ITEM": "Product B"}
  ],
  "copies": 1
}
```

List available templates: `GET /labels/templates`

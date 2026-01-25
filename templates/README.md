# Templates Directory

## Purpose

This directory stores **gLabels template files** used by the label printing service.

## File Format

- `.glabels` - Standard gLabels template file (regardless of compression)

## How to Use

### 1. Place your template

Put your gLabels template file directly into this directory:

```text
templates/
├── your_custom_template.glabels      ← your template file
````

### 2. API Usage

When calling `POST /labels/print`, use the filename (without path):

```json
{
  "template_name": "your_custom_template.glabels",
  "data": [
    {"DATA1": "D1", "DATA2": "D01"},
    {"DATA1": "D2", "DATA2": "D02"}
  ],
  "copies": 1
}
```

## Template Requirements

- **CSV field mapping**: The field names defined in the template must exactly match the keys in the API `data` object.
- **UTF-8 encoding**: Ensure UTF-8 encoding to correctly render Chinese or other special characters.
- **Testing recommendation**: Test your template in the gLabels desktop application before placing it here.

## Example

Suppose `your_custom_template.glabels` defines these fields:

- `DATA1` - Field 1
- `DATA2` - Field 2

Corresponding API request:

```json
{
  "template_name": "your_custom_template.glabels",
  "data": [
    {"DATA1": "D1", "DATA2": "D01"},
    {"DATA1": "D2", "DATA2": "D02"}
  ],
  "copies": 2
}
```

# Test Suite

Unit tests for glabels-batch-service, focusing on core functionality and business logic.

## Quick Start

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html

# Specific test
pytest tests/test_glabels_engine.py -v
```

## Test Coverage: 51 Tests

| Test File | Tests | Purpose |
|-----------|-------|---------|
| `test_glabels_engine.py` | 7 | CLI wrapper and subprocess handling |
| `test_job_manager.py` | 7 | Job lifecycle and worker management |
| `test_template_service.py` | 6 | Template discovery and parsing |
| `test_label_print.py` | 16 | CSV generation, batching, PDF merging |
| `test_api_endpoints.py` | 11 | API validation and error handling |
| `test_integration.py` | 4 | End-to-end workflows |

## Key Test Areas

### GlabelsEngine (`test_glabels_engine.py`)

- Successful PDF generation via CLI
- Error handling and timeout scenarios
- Missing file detection
- Output truncation for long errors

### JobManager (`test_job_manager.py`)

- Job submission and queuing
- Async worker processing
- Job completion and failure tracking
- Automatic cleanup (retention policy)

### TemplateService (`test_template_service.py`)

- Template discovery in directories
- Field extraction from `.glabels` files
- Format detection (CSV/TSV)
- Invalid template handling

### LabelPrintService (`test_label_print.py`)

- JSON to CSV conversion
- Field ordering consistency
- Batch splitting (respects `MAX_LABELS_PER_BATCH`)
- PDF merging for multi-batch jobs
- Temporary file cleanup

### API Endpoints (`test_api_endpoints.py`)

- Request validation (template name, data format)
- Error responses (404, 409, 410)
- Schema validation

### Integration Tests (`test_integration.py`)

- Full workflow: template → job → PDF
- Component interaction
- Error propagation

## Testing Philosophy

- **Fast execution**: Complete suite runs in <1 second
- **Mock external dependencies**: Filesystem, subprocess, network
- **Test business logic**: Focus on critical functionality, not framework features
- **Easy maintenance**: Clear test names and focused assertions

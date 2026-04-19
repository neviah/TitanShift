# TitanShift Setup Guide

This guide is for first-time setup of TitanShift on a local machine.

## Prerequisites

- Python 3.11+
- Node.js 20+ (for frontend)
- Git
- Optional: LM Studio if you want local model inference

## 1) Install the project

From the repository root:

```bash
pip install -r requirements.txt
pip install -e .
```

The editable install exposes both CLI entry points:

- harness
- titanshift

## 2) Initialize configuration

Run the first-run wizard:

```bash
titanshift init
```

The wizard asks for:

- Model backend (lmstudio, openai_compatible, or local_stub)
- Workflow mode (lightning or superpowered)
- Whether cloud adapters are allowed

It writes harness.config.json and creates harness_data/.

If a config already exists, it can back up to harness.config.json.bak.

## 3) Configure API keys (optional but recommended)

For local overrides, copy the example file:

```bash
cp harness.config.local.example.json harness.config.local.json
```

Then set local values for api.api_key and api.admin_api_key.

## 4) Start the backend API

```bash
titanshift serve-api --host 127.0.0.1 --port 8000
```

Useful health checks:

```bash
titanshift status
titanshift print-config
```

## 5) Run the frontend (optional)

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

## 6) Validate installation

Run superpowered smoke tests:

```bash
python -m pytest tests/test_smoke.py -k "superpowered" -v --tb=short
```

If the run is healthy, you should see all selected superpowered tests passing.

## Common startup patterns

### Backend only

```bash
titanshift serve-api
```

### Backend + frontend

Terminal 1:

```bash
titanshift serve-api
```

Terminal 2:

```bash
cd frontend
npm run dev
```

## Troubleshooting

- If CLI command is not found after install, restart terminal and run pip install -e . again.
- If LM Studio checks fail, verify base_url and model settings in harness.config.json.
- If requests fail with 401/403, verify read/admin API key settings and headers.

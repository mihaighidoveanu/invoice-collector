# invoice-collector

A FastAPI service that collects monthly invoices from Gmail using a bank statement as the source of truth. Given a bank statement PDF, the agent identifies all vendors and amounts for the target month, generates Gmail search rules per vendor, searches Gmail for matching invoices, downloads and saves them locally, and produces an Excel report for the accountant.

---

## Setup

### 1. Create the virtual environment and install dependencies

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `ANTHROPIC_API_KEY` — your Anthropic API key
- `GMAIL_CREDENTIALS_PATH` — path to your Google OAuth2 `credentials.json`

To obtain Gmail credentials: Google Cloud Console → APIs & Services → Credentials → Create OAuth 2.0 Client ID (Desktop app) → download the JSON and save it as `credentials.json`.

### 3. First run — Gmail OAuth2 browser flow

The first time the pipeline runs, a browser window will open asking you to authorise Gmail access. The token is saved to `token.json` and reused silently on subsequent runs.

---

## Running the server

```bash
uvicorn main:app --reload
```

---

## Running the pipeline

Upload a bank statement PDF:

```bash
curl -X POST http://localhost:8000/run \
  -F "bank_statement=@/path/to/statement.pdf"
```

Or use the slash command inside Claude Code:

```
/run-pipeline /path/to/statement.pdf
```

Response:

```json
{
  "status": "ok",
  "invoices_found": 12,
  "invoices_missing": 2,
  "report_path": "invoices/report_2025-03.xlsx",
  "invoice_dir": "invoices/"
}
```

---

## Exporting Excel manually

If you already have a JSON report and want to re-export it:

```bash
python tools/export_excel.py invoices/report_2025-03.json
```

---

## Running tests

```bash
pytest tests/ -v --tb=short
```

Or use the slash command inside Claude Code:

```
/test-all
```

---

## Output files

All output lands in `invoices/`:

| File | Description |
|------|-------------|
| `invoices/{Vendor}/invoice.pdf` | Downloaded attachment per vendor |
| `invoices/report_2025-03.json` | Machine-readable pipeline report |
| `invoices/report_2025-03.xlsx` | Excel report for the accountant |
| `invoices/pipeline_2025-03.log` | Per-run log |

# invoice-collector

Collects monthly invoices from Gmail using a bank statement as the source of truth. Given a bank statement PDF, the agent extracts all vendors and amounts for the target month, searches Gmail for matching invoices, downloads them locally, and produces an Excel report for the accountant.

---

## Setup

### 1. Create the virtual environment and install dependencies

```bash
uv venv --python 3.11
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

## Running the pipeline

### CLI (primary)

```bash
.venv/bin/python cli.py /path/to/statement.pdf
```

Output is written to `invoices/runs/{timestamp}/`.

### FastAPI server

```bash
.venv/bin/uvicorn main:app --reload
```

Then upload a bank statement:

```bash
curl -X POST http://localhost:8000/run \
  -F "bank_statement=@/path/to/statement.pdf"
```

Or use the slash command inside Claude Code:

```
/run-pipeline /path/to/statement.pdf
```

---

## Running tests

**Unit tests** — no external dependencies:

```bash
.venv/bin/python -m pytest tests/unit -v --tb=short
```

Or via Claude Code slash command: `/unit-test`

**Integration tests** — require live Gmail and Anthropic credentials:

```bash
.venv/bin/python -m pytest tests/integration/test_integrations.py::test_gmail_connection -v --tb=short
.venv/bin/python -m pytest tests/integration/test_integrations.py::test_llm_connection -v --tb=short
```

Or via Claude Code slash commands: `/test-gmail`, `/test-llm`

**Real tests** — run the full pipeline against a real bank statement PDF:

```bash
TEST_STATEMENT_PDF=/path/to/statement.pdf .venv/bin/python -m pytest tests/real -v -s
```

---

## Output files

Each pipeline run creates a timestamped directory under `invoices/runs/`:

| File | Description |
|------|-------------|
| `invoices/runs/{ts}/{Vendor}/` | Downloaded attachments per vendor |
| `invoices/runs/{ts}/report.json` | Machine-readable pipeline report |
| `invoices/runs/{ts}/report.xlsx` | Excel report for the accountant |
| `invoices/runs/{ts}/pipeline.log` | Per-run log |
| `invoices/runs/{ts}/meta.json` | Run metadata (timestamp, month, statement path) |

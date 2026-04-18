# Invoice Agent — implementation plan

## What this project does

A FastAPI service that collects monthly invoices from Gmail using a bank statement as the source of truth. Given a bank statement PDF and a target month, the agent identifies all vendors and amounts, generates Gmail search rules per vendor, searches Gmail for matching invoices, downloads and saves them locally, and produces an Excel report for the accountant.

---

## Data models (models.py)

```python
class Transaction(BaseModel):
    vendor: str                  # normalized vendor name
    amount: float
    currency: str
    date: date
    raw_description: str         # original bank text, kept for audit

class SearchRule(BaseModel):
    vendor: str
    subject_keywords: list[str]
    body_keywords: list[str]
    attachment_filename_keywords: list[str]

class EmailMatch(BaseModel):
    email_id: str
    subject: str
    sender: str
    snippet: str
    attachment_filenames: list[str]
    date: date

class AttachmentReading(BaseModel):
    is_invoice: bool
    vendor: str | None = None
    amount: float | None = None
    date: date | None = None
    confidence: float | None = None

class AmbiguousNormalization(BaseModel):
    raw_description: str
    normalized_name: str
    confidence_note: str

class FailureReason(str, Enum):
    AMOUNT_MISMATCH = "No invoice with a matching amount found in the analysis period"
    DUPLICATE_AMOUNT_VENDOR_MISMATCH = "Multiple invoices share the same amount; vendor name matching failed to resolve"
    LLM_CALL_FAILED = "LLM call failed after all retries"
    ATTACHMENT_NOT_INVOICE = "Downloaded attachment is not an invoice"
    ATTACHMENT_UNREADABLE = "Attachment PDF has insufficient text (scanned/image PDF)"
    NO_ATTACHMENTS_IN_EMAIL = "Matched email has no downloadable attachments"

class InvoiceResult(BaseModel):
    transaction: Transaction
    email_id: str | None = None
    attachment_path: Path | None = None
    status: Literal["found", "missing"]
    failure_reason: FailureReason | None = None  # set when status="missing"
```

---

## Phase 1 — Statement parser (agent/statement_parser.py)

**Input:** PDF file path
**Output:** `list[Transaction]` + `list[AmbiguousNormalization]` for the report audit tab

1. Extract all text with `pdfplumber`, filter to rows in the target month.
2. Send to LLM requesting a JSON array of transactions. Instruct it to normalize vendor names (e.g. `AMZN MKTP US*AB12` → `Amazon`) and flag low-confidence normalizations.
3. Parse and validate JSON into `list[Transaction]`.
4. **Log all normalizations as a single block** at INFO level after parsing completes. One contiguous section in the log with every `raw_description → vendor` mapping, so there's exactly one place to review all LLM vendor-mapping decisions:
   ```
   === Vendor normalizations (14 transactions) ===
   "AMZN MKTP US*AB12"  → "Amazon"
   "GOOGLE *CLOUD"      → "Google Cloud"
   "SQ *COFFEE SHOP"    → "Square Coffee Shop"  [ambiguous]
   ...
   === End vendor normalizations ===
   ```

**Tests:** mock LLM; fixture PDF with ≥5 transactions including one ambiguous vendor name.

---

## Phase 2 — Rule builder (agent/rule_builder.py)

**Input:** `list[Transaction]`
**Output:** `list[SearchRule]`

Fully deterministic — no LLM calls:

- `subject_keywords`: vendor name tokens + `["invoice", "receipt", "factura", "bill"]`
- `body_keywords`: amount as formatted string + vendor name tokens
- `attachment_filename_keywords`: vendor name tokens + `["invoice", "receipt", "factura"]`

Date filtering is a pipeline-level concern (analysis window passed to `list_emails_with_attachments`), not per-rule.

**Tests:** unit tests with diverse transaction fixtures; no external calls.

---

## Phase 3 — Gmail tools (agent/gmail_tools.py)

**OAuth2:** browser flow on first run if no token file exists; silent load + refresh on subsequent runs.

**`list_emails_with_attachments(after: date, before: date) -> list[EmailMatch]`**
- Single Gmail query: `has:attachment after:YYYY/MM/DD before:YYYY/MM/DD`
- Returns email metadata only (id, subject, sender, date, snippet, attachment filenames). No downloads.

**`download_attachment(email_id: str, filename: str, vendor: str) -> Path`**
- Downloads to `INVOICE_OUTPUT_DIR/{vendor}/`. Returns local path.

**Tests:** mock Gmail API with `unittest.mock`; no real credentials needed.

---

## Phase 4 — Attachment reader (agent/attachment_reader.py)

**Input:** local PDF path
**Output:** `AttachmentReading(is_invoice: bool, vendor, amount, date, confidence)`

pdfplumber-first gate:
1. Extract text with `pdfplumber`.
2. If text ≥ 50 chars → send to LLM: *"Is this an invoice? If yes, return `{is_invoice, vendor, amount, date}`. If no, return `{is_invoice: false}`."*
3. If text < 50 chars → return `AttachmentReading(is_invoice=False)` without calling the LLM.

LLM is only called when the gate condition is met.

**Note:** scanned/image PDFs yield near-zero text from pdfplumber and are not supported. They fall through the gate and the parent invoice is marked `missing`.

**Tests:** two fixtures — text invoice, non-invoice (including short-text PDF). Mock LLM calls.

---

## Phase 5 — Pipeline (agent/pipeline.py)

**Input:** `bank_statement_path: Path`
**Output:** `list[InvoiceResult]`

The target month is derived from the parsed transactions (most common month among transaction dates). The analysis period spans that month through the end of the following month (e.g. for `2025-03`: `2025-03-01` → `2025-04-30`).

1. Parse bank statement → `list[Transaction]` (statement_parser).
2. Build `list[SearchRule]` for all transactions (rule_builder).
3. Call `list_emails_with_attachments(period_start, period_end)` → `list[EmailMatch]`.

For each email:

4. **Metadata match:** check the email against every `SearchRule` (subject keywords, attachment filename keywords).
5. If a rule matches: download attachment, read it with attachment_reader. The invoice is linked to the matched transaction.
6. If no rule matches: **fallback to attachment content** — download the attachment, read it with attachment_reader. If it is an invoice, add it to the unmatched invoice pool for amount-based matching in step 7.

After all emails are processed, match invoices to transactions:

7. **Amount-based matching:** group confirmed invoices (from attachment_reader) by amount. For each transaction:
   - **Unique amount match:** exactly one invoice has the same amount → `status="found"`.
   - **Multiple invoices with same amount:** attempt vendor-name match between the transaction vendor and the invoice vendor (from attachment_reader). If one matches → `status="found"`. If none or multiple match → `status="missing"`, `failure_reason=DUPLICATE_AMOUNT_VENDOR_MISMATCH`.
   - **No invoice with matching amount** → `status="missing"`, `failure_reason=AMOUNT_MISMATCH`.
8. Each invoice can only be claimed once; once assigned to a transaction it is removed from the pool.

**Tests:** integration test with mocked statement parser + Gmail + LLM; fixtures covering: clean unique-amount match, duplicate-amount with successful vendor tiebreak, duplicate-amount with failed vendor tiebreak, transaction with no email → missing.

---

## Phase 6 — Report builder (agent/report_builder.py)

**Input:** `list[InvoiceResult]`, `list[AmbiguousNormalization]`, output path
**Output:** `.json` file

Serializes pipeline results into a structured JSON report via a dedicated Pydantic model:

```python
class PipelineReport(BaseModel):
    run_date: date
    target_month: str               # e.g. "2025-03"
    invoices_found: int
    invoices_missing: int
    results: list[InvoiceResult]
    vendor_normalizations: list[AmbiguousNormalization]
    errors: list[str]               # one-line summary per missing/failed invoice
```

Writes to `INVOICE_OUTPUT_DIR/report_{month}.json`.

**Tests:** fixture with one result of each status; assert JSON structure and error list contents.

---

## Excel export utility (tools/export_excel.py)

Standalone script — reads `report_{month}.json`, produces the `.xlsx` the accountant expects.

```
python tools/export_excel.py invoices/report_2025-03.json
```

**Sheet 1 — "Invoices":** columns: Vendor, Date, Amount, Currency, Status, Email Subject, Attachment Path, Failure Reason
Row fill colors: `found` → light green · `missing` → light red

**Sheet 2 — "Vendor Normalizations":** raw bank text, normalized name, LLM confidence note.

`openpyxl` is a dependency of this utility only, not the pipeline.

---

## Phase 7 — FastAPI endpoint (main.py)

`POST /run` — multipart form: `bank_statement` (PDF)
Response:
```json
{ "status": "ok", "invoices_found": 12, "invoices_missing": 2,
  "report_path": "invoices/report_2025-03.xlsx", "invoice_dir": "invoices/" }
```

- Save uploaded PDF to temp file → run full pipeline (target month derived internally) → write Excel report to `INVOICE_OUTPUT_DIR/report_{derived_month}.xlsx`
- Log progress to `pipeline_{derived_month}.log` via background task

---

## Project slash commands (.claude/commands/)

**`run-pipeline.md`**
```
curl -X POST http://localhost:8000/run \
  -F "bank_statement=@$ARGUMENTS" \
```

**`test-all.md`**
```
pytest tests/ -v --tb=short
```

---

## LLM retry policy

All LLM calls (statement parser in Phase 1, attachment reader in Phase 4) use the same retry strategy:

- On failure (network error, malformed response, API error): retry up to `LLM_MAX_RETRIES` times (configured in `.env`, default 3) with exponential backoff.
- If all retries exhausted: treat as zero results (Phase 1) or `AttachmentReading(is_invoice=False)` (Phase 4), and propagate the error into `InvoiceResult.notes`.

---

## Escalation — stop and confirm before implementing

- Any LLM call not specified in this plan
- Gmail queries that could return hundreds of results
- Changes to the retry cap or retry logic
- Excel schema changes that affect the accountant's workflow

---

## Implementation order

Build and test each phase in sequence. `pytest tests/ -v` and `ruff check .` must pass before moving on.

1. Scaffold — all empty files, `.env.example`, `requirements.txt`
2. `config.py` + `models.py`
3. `statement_parser.py`
4. `rule_builder.py`
5. `gmail_tools.py`
6. `attachment_reader.py`
7. `pipeline.py`
8. `report_builder.py`
9. `main.py`
10. Slash commands + `README.md` + final lint pass

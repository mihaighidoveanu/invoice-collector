# Workspace Evaluation vs CLAUDE.md Requirements

## Context
Auditing the invoice-collector codebase against its CLAUDE.md specification to identify gaps,
violations, redundancies, and improvement opportunities. No code is being written — this is a
read-only evaluation whose output is a structured findings report.

---

## CLAUDE.md Requirements Recap

**Goal:** Collect monthly invoices from Gmail using a bank statement PDF as source of truth.

**Strategy (6 phases):**
1. Extract month/year from bank statement
2. Extract vendor, amount, date for all transactions
3. Iterate over emails with attachments from statement month + one month after
4. Map vendor and amount to invoices from emails
5. Download invoices
6. Produce a report (found + missing)

**Termination condition:** Stop when *either* (a) all transactions have a matching invoice **or** (b) all emails from the two-month window have been processed.

**Constraints:**
1. Python (latest stable)
2. LLM via **LangChain AWS Bedrock** — cheapest model that gets the job done
3. Bank statements, emails, attachments must be private
4. Everything must have a justifiable reason

---

## Findings

### CRITICAL — Constraint violations

#### C1. Wrong LLM provider (Constraint #2)
- **Violated:** `langchain-anthropic` is used instead of `langchain-aws` (AWS Bedrock)
- **Evidence:**
  - `requirements.txt` line 7: `langchain-anthropic==0.1.20`
  - `config.py` line 10: `anthropic_api_key: str = ""`
  - `agent/statement_parser.py` line 7: `from langchain_anthropic import ChatAnthropic`
  - `agent/attachment_reader.py` line 13: `from langchain_anthropic import ChatAnthropic`
- **Impact:** Billing goes to Anthropic API instead of AWS Bedrock; breaks Constraint #2 entirely.

#### C2. Wrong model — not cheapest (Constraint #2)
- **Violated:** `claude-sonnet-4-6` is configured as default (`config.py` line 11)
- Sonnet is mid-tier; the cheapest capable model on Bedrock would be the Haiku equivalent.
- **Impact:** Higher per-run cost than necessary, directly violating "cheapest model that gets the job done."

---

### BUGS — Strategy not fully implemented

#### B1. `attachment_path` always `None` in found results
- `pipeline.py` line 248–249: `attachment_path=None  # path not surfaced here`
- The comment claims `report_builder` uses the pool, but `report_builder.py` only receives
  `list[InvoiceResult]`, which all have `attachment_path=None`.
- **Impact:** The Excel report's "Attachment Path" column will always be blank for found invoices.
  Accountant cannot navigate to downloaded files from the report.

#### B2. No early termination when all transactions matched
- **Required by CLAUDE.md:** stop processing emails once all transactions have invoices.
- **Actual behaviour:** `pipeline.py` iterates over every email unconditionally, downloads every
  attachment, and calls the LLM on each before matching.
- **Impact:** Unnecessary LLM cost and latency when invoices are found early.

---

### UNNECESSARY — Packages / code with no justification

#### U1. `langchain-community` is unused
- `requirements.txt` line 8: `langchain-community==0.2.10`
- No file in the codebase imports from `langchain_community`.
- **Impact:** Extra dependency with no benefit; increases install size and attack surface.

#### U2. `evaluations/` directory is empty
- Contains only `__init__.py`. No evaluation code, no fixtures, nothing.
- Adds noise without value.

---

### MINOR — Improvement opportunities

#### M1. Python version target is outdated
- `pyproject.toml`: `target-version = "py311"`
- CLAUDE.md says "latest stable version" — that is Python 3.13 as of April 2026.
- No incompatibilities are expected; it's a config update only.

---

## What Is Correct

- **Strategy phases 1–6** are implemented and correctly structured.
- **Analysis window** (`_analysis_window` in pipeline.py): correctly covers target month + following
  month as required (period_end is exclusive first-of-month after the window).
- **Privacy / Constraint #3:** `invoices/`, `.env`, `token.json`, `credentials.json` all excluded
  from git. Output paths are local only.
- **Test coverage** is comprehensive — all phases have unit tests with mocked I/O.
- **Retry logic** (tenacity) is properly applied to both LLM call sites.
- **Deterministic rule builder** avoids unnecessary LLM calls (good cost discipline).
- **pdfplumber-first gate** in attachment_reader avoids LLM calls on scanned PDFs.

---

## Recommended Fixes (Priority Order)

| Priority | Item | File(s) |
|----------|------|---------|
| P0 | Switch to `langchain-aws` + Bedrock; update `config.py` and both `_build_llm()` functions | `requirements.txt`, `config.py`, `agent/statement_parser.py`, `agent/attachment_reader.py` |
| P0 | Set cheapest Bedrock model as default (e.g. `amazon.nova-micro-v1:0` or `anthropic.claude-haiku-4-5`) | `config.py` |
| P1 | Fix `attachment_path` always `None` — populate it from the invoice pool in `_match_transaction` or report_builder | `agent/pipeline.py` |
| P1 | Add early exit when all transactions are matched (stop email loop) | `agent/pipeline.py` |
| P2 | Remove `langchain-community` from `requirements.txt` | `requirements.txt` |
| P3 | Update `pyproject.toml` target-version to py313 | `pyproject.toml` |
| P3 | Remove empty `evaluations/` directory or add a stub evaluation | `evaluations/` |

---

## Verification (after fixes)

1. `pytest tests/ -v --tb=short` — all tests pass
2. `ruff check .` — no linting errors  
3. Manual run: `POST /run` with a real bank statement PDF → Excel report shows non-null attachment
   paths for found invoices and terminates early when all transactions are matched.

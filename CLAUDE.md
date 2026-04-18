# Invoice Agent — project conventions

## What this project does

A FastAPI service that collects monthly invoices from Gmail using a bank statement as the source of truth. Given a bank statement PDF, the agent identifies all vendors and amounts for the target month, generates Gmail search rules per vendor, searches Gmail for matching invoices, downloads and saves them locally, and produces an Excel report for the accountant.

## Stack
- Python 3.11+
- FastAPI, LangChain, langchain-aws (AWS Bedrock via ChatBedrockConverse)
- pdfplumber (text PDFs), openpyxl, pydantic-settings
- Linting: ruff

## Autonomy

For decisions that impact user experience, project cost, or performance, escalate to the user, explain trade-offs to me and implement only after I decide.

## Config
- All tunables live in `.env` and are loaded via `pydantic-settings` in `config.py`
- Never hardcode model names, paths, or numeric thresholds anywhere else

## Code style
- Type-annotate all function signatures
- Use `Literal`, `Path`, and `date` from stdlib — never bare strings for status values
- Pydantic models for all data boundaries (API input/output, inter-module data)
- `ruff check . && ruff format --check .` must pass before any phase is considered done

## Error handling
- The invoice processing pipeline must never raise — catch all per-transaction exceptions, set `status="ambiguous"`, store error in `notes`
- LLM call failures are caught and treated as zero results (triggers retry logic)

## LLM calls
- All LLM calls go through LangChain
- Before adding any LLM call not already in `PLAN.md`, stop and confirm with the user

## Testing
- Every module has a corresponding test file in `tests/`
- LLM and Gmail API calls are always mocked in tests — no real credentials required
- Run `pytest tests/ -v` after completing each phase

## Evaluations
- Evaluations are tests on real data on golden datasets
- Every module has a corresponding evaluation file in evaluations/
- LLM and Gmail API calls are not mocked in evaluation - use the real credentials

## Gmail
- OAuth2 only — browser flow on first run, token persisted to `GMAIL_TOKEN_PATH`

## Project layout

- **Root:** `CLAUDE.md`, `.env` / `.env.example`, `requirements.txt`, `main.py`, `config.py`, `models.py`
- **agent/:** pipeline phases — `statement_parser.py`, `rule_builder.py`, `gmail_tools.py`, `attachment_reader.py`, `pipeline.py`, `report_builder.py`
- **tools/:** utilities — `export_excel.py`
- **invoices/:** output directory (gitignored) — generated reports, invoices, logs
- **tests/:** unit & integration tests with `fixtures/` subfolder; one test file per agent module
- **evaluations/:** evaluation files on real data; one eval file per agent module
- **claude-workbench/:** implementation plan and tracking
- **.claude/commands/:** slash commands (`run-pipeline.md`, `test-all.md`)

"""Phase 7 — FastAPI endpoint.

POST /run — accepts a bank statement PDF, runs the full pipeline,
writes an Excel report, and returns a summary JSON response.
"""

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from agent.attachment_reader import read_attachment
from agent.pipeline import _derive_target_month, run_pipeline
from agent.report_builder import build_report
from agent.run_artifacts import RunArtifacts
from agent.statement_parser import _extract_text, parse_statement
from config import settings
from tools.export_excel import export

app = FastAPI(title="Invoice Collector", version="1.0.0")


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class RunResponse(BaseModel):
    status: str
    invoices_found: int
    invoices_missing: int
    report_path: str
    invoice_dir: str
    run_dir: str


# ---------------------------------------------------------------------------
# Background logging helper
# ---------------------------------------------------------------------------


def _setup_file_logger(log_path: Path) -> logging.FileHandler:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    return handler


def _teardown_file_logger(handler: logging.FileHandler) -> None:
    handler.close()
    logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@app.post("/run", response_model=RunResponse)
async def run(
    background_tasks: BackgroundTasks,
    bank_statement: UploadFile = File(..., description="Bank statement PDF"),
) -> RunResponse:
    """Run the invoice collection pipeline for the uploaded bank statement."""

    if bank_statement.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=400,
            detail=f"Expected a PDF file, got: {bank_statement.content_type}",
        )

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = settings.invoice_output_dir / "runs" / timestamp

    # Save upload to a temp file so pdfplumber can read it
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await bank_statement.read())
        tmp_path = Path(tmp.name)

    # Set up file logger before pipeline so all logs are captured
    log_handler = _setup_file_logger(run_dir / "pipeline.log")
    try:
        results, month = run_pipeline(tmp_path, run_dir=run_dir)
    except Exception as exc:
        logging.getLogger(__name__).error("Pipeline failed: %s", exc)
        _teardown_file_logger(log_handler)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    _teardown_file_logger(log_handler)

    # Write JSON report and Excel into the run directory
    json_path = run_dir / "report.json"
    xlsx_path = run_dir / "report.xlsx"
    report = build_report(results, month, output_path=json_path)
    export(json_path, xlsx_path)

    return RunResponse(
        status="ok",
        invoices_found=report.invoices_found,
        invoices_missing=report.invoices_missing,
        report_path=str(xlsx_path),
        invoice_dir=str(settings.invoice_output_dir),
        run_dir=str(run_dir),
    )


if __name__ == '__main__':

    run_dir = Path('output/')
    pdf_path = 'input/0_Extrase_RO73BTRLRONCRT0CR2266601_2026-01-01_2026-01-31_CALEIDOSCOP_PRIME_BUZZ_S_R_L.PDF'
    
    text = _extract_text(pdf_path)
    print(text)
    
    # artifacts = RunArtifacts(run_dir, str(bank_statement_path)) if run_dir else None

    # # --- Phase 1: parse statement ---
    # transactions, ambiguous = parse_statement(
    #     bank_statement_path
    # )
    # print(transactions)
    
    # if artifacts:
    #     artifacts.save("01_transactions.json", transactions)
    #     artifacts.save("01_ambiguous.json", ambiguous)

    # derived_month = _derive_target_month(transactions)
    # if artifacts:
    #     artifacts.save_meta(derived_month)

    # # period_start, period_end = _analysis_window(derived_month)
    # # logger.info(
    # #     "Target month: %s | Analysis window: %s → %s",
    # #     derived_month,
    # #     period_start,
    # #     period_end,
    # # )

    # # # --- Phase 2: build rules ---
    # # rules = build_rules(transactions)
    # # if artifacts:
    # #     artifacts.save("02_rules.json", rules)

    # # # --- Phase 3: fetch emails ---
    # # emails = list_emails_with_attachments(period_start, period_end)
    # # if artifacts:
    # #     artifacts.save("03_emails.json", emails)
    # # logger.info("Processing %d emails against %d transactions", len(emails), len(transactions))

    # # # Pool of confirmed invoices: mapping from (email_id, filename) → (reading, email, local_path)
    # # # Keyed to prevent double-claiming the same attachment.
    # # invoice_pool: dict[tuple[str, str], tuple[AttachmentReading, EmailMatch, Path]] = {}

    # # # Transactions directly matched by metadata rule: tx_vendor → (email_id, filename)
    # # direct_matches: dict[str, tuple[str, str]] = {}

    # # # Precompute per-amount counts for early-exit check (B2)
    # # tx_amount_counts: Counter[float] = Counter(tx.amount for tx in transactions)

    # # readings_log: list[dict] = []

    # # for email in emails:
    # #     if not email.attachment_filenames:
    # #         continue

    # #     filename = email.attachment_filenames[0]
    # #     pool_key = (email.email_id, filename)

    # #     matched_rule = _find_matching_rule(email, rules)

    # #     if matched_rule:
    # #         # --- Metadata match: download and read ---
    # #         try:
    # #             local_path = download_attachment(email.email_id, filename, matched_rule.vendor)
    # #             reading = read_attachment(local_path)
    # #         except Exception as exc:
    # #             logger.warning("Failed processing attachment for %s: %s", matched_rule.vendor, exc)
    # #             continue

    # #         readings_log.append({
    # #             "email_id": email.email_id,
    # #             "filename": filename,
    # #             "vendor_dir": matched_rule.vendor,
    # #             "reading": reading.model_dump(mode="json"),
    # #         })

    # #         if reading.is_invoice:
    # #             invoice_pool[pool_key] = (reading, email, local_path)
    # #             direct_matches[matched_rule.vendor] = pool_key
    # #     else:
    # #         # --- Fallback: read attachment content for amount-based matching ---
    # #         try:
    # #             # We don't know the vendor yet; use a generic directory
    # #             local_path = download_attachment(email.email_id, filename, "unknown")
    # #             reading = read_attachment(local_path)
    # #         except Exception as exc:
    # #             logger.debug("Fallback download failed for email %s: %s", email.email_id, exc)
    # #             continue

    # #         readings_log.append({
    # #             "email_id": email.email_id,
    # #             "filename": filename,
    # #             "vendor_dir": "unknown",
    # #             "reading": reading.model_dump(mode="json"),
    # #         })

    # #         if reading.is_invoice:
    # #             invoice_pool[pool_key] = (reading, email, local_path)

    # #     # Early exit: stop scanning when the pool already covers all transaction amounts
    # #     pool_amount_counts: Counter[float] = Counter(
    # #         r.amount for r, _, _ in invoice_pool.values() if r.amount is not None
    # #     )
    # #     if all(pool_amount_counts[a] >= n for a, n in tx_amount_counts.items()):
    # #         logger.info("All transaction amounts covered; stopping email scan early.")
    # #         break

    # # if artifacts:
    # #     artifacts.save("04_readings.json", readings_log)

    # # # --- Phase 7: amount-based matching ---
    # # # Group confirmed invoices by amount
    # # amount_index: dict[float, list[tuple[str, str]]] = defaultdict(list)
    # # for pool_key, (reading, _email, _path) in invoice_pool.items():
    # #     if reading.amount is not None:
    # #         amount_index[reading.amount].append(pool_key)

    # # results: list[InvoiceResult] = []
    # # claimed: set[tuple[str, str]] = set()

    # # for tx in transactions:
    # #     try:
    # #         result = _match_transaction(tx, amount_index, invoice_pool, claimed)
    # #         results.append(result)
    # #     except Exception as exc:
    # #         logger.error("Unexpected error matching transaction %s: %s", tx.vendor, exc)
    # #         results.append(
    # #             InvoiceResult(
    # #                 transaction=tx,
    # #                 status="missing",
    # #                 failure_reason=FailureReason.LLM_CALL_FAILED,
    # #                 notes=str(exc),
    # #             )
    # #         )

    # # if artifacts:
    # #     artifacts.save("05_results.json", results)
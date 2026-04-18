"""Phase 7 — FastAPI endpoint.

POST /run — accepts a bank statement PDF, runs the full pipeline,
writes an Excel report, and returns a summary JSON response.
"""

import logging
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from agent.pipeline import run_pipeline
from agent.report_builder import build_report
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


# ---------------------------------------------------------------------------
# Background logging helper
# ---------------------------------------------------------------------------


def _setup_file_logger(month: str) -> logging.FileHandler:
    log_dir = settings.invoice_output_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_dir / f"pipeline_{month}.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
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

    # Save upload to a temp file so pdfplumber can read it
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(await bank_statement.read())
        tmp_path = Path(tmp.name)

    try:
        results, ambiguous, month = run_pipeline(tmp_path)
    except Exception as exc:
        logging.getLogger(__name__).error("Pipeline failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    # Write JSON report
    report = build_report(results, ambiguous, month)

    # Write Excel report
    json_path = settings.invoice_output_dir / f"report_{month}.json"
    xlsx_path = settings.invoice_output_dir / f"report_{month}.xlsx"
    export(json_path, xlsx_path)

    # Background: attach a per-run log file (best-effort)
    log_handler = _setup_file_logger(month)
    background_tasks.add_task(_teardown_file_logger, log_handler)

    return RunResponse(
        status="ok",
        invoices_found=report.invoices_found,
        invoices_missing=report.invoices_missing,
        report_path=str(xlsx_path),
        invoice_dir=str(settings.invoice_output_dir),
    )

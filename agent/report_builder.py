"""Phase 6 — Report builder.

Serializes pipeline results to a structured JSON file.
"""

import logging
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from config import settings
from models import AmbiguousNormalization, InvoiceResult

logger = logging.getLogger(__name__)


class PipelineReport(BaseModel):
    run_date: date
    target_month: str
    invoices_found: int
    invoices_missing: int
    results: list[InvoiceResult]
    vendor_normalizations: list[AmbiguousNormalization]
    errors: list[str]


def _build_errors(results: list[InvoiceResult]) -> list[str]:
    errors: list[str] = []
    for r in results:
        if r.status == "missing":
            reason = r.failure_reason.value if r.failure_reason else "unknown reason"
            tx = r.transaction
            line = f"{tx.vendor} ({tx.amount} {tx.currency}): {reason}"
            if r.notes:
                line += f" | {r.notes}"
            errors.append(line)
    return errors


def build_report(
    results: list[InvoiceResult],
    ambiguous: list[AmbiguousNormalization],
    target_month: str,
    output_path: Path | None = None,
) -> PipelineReport:
    """Build and persist a PipelineReport.

    Args:
        results: Invoice results from the pipeline.
        ambiguous: Vendor normalizations flagged as ambiguous.
        target_month: The derived target month string (YYYY-MM).
        output_path: Override the default output path. If None, writes to
            INVOICE_OUTPUT_DIR/report_{target_month}.json.

    Returns:
        The PipelineReport instance.
    """
    found = sum(1 for r in results if r.status == "found")
    missing = sum(1 for r in results if r.status == "missing")

    report = PipelineReport(
        run_date=date.today(),
        target_month=target_month,
        invoices_found=found,
        invoices_missing=missing,
        results=results,
        vendor_normalizations=ambiguous,
        errors=_build_errors(results),
    )

    if output_path is None:
        output_path = settings.invoice_output_dir / f"report_{target_month}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info("Report written to %s", output_path)

    return report

"""CLI entry point — runs the full invoice collection pipeline without a server."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from agent.pipeline import run_pipeline
from agent.report_builder import build_report
from config import settings
from tools.export_excel import export


def _setup_logging(log_path: Path) -> logging.FileHandler:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Run invoice collection pipeline")
    parser.add_argument("statement", type=Path, help="Path to bank statement PDF")
    args = parser.parse_args()

    if not args.statement.exists():
        print(f"Error: {args.statement} does not exist", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_dir = settings.invoice_output_dir / "runs" / timestamp

    log_handler = _setup_logging(run_dir / "pipeline.log")
    try:
        results, month = run_pipeline(args.statement, run_dir=run_dir)
    finally:
        log_handler.close()
        logging.getLogger().removeHandler(log_handler)

    json_path = run_dir / "report.json"
    xlsx_path = run_dir / "report.xlsx"
    report = build_report(results, month, output_path=json_path)
    export(json_path, xlsx_path)

    print(f"Done. Found: {report.invoices_found} | Missing: {report.invoices_missing}")
    print(f"Report: {xlsx_path}")
    print(f"Run dir: {run_dir}")


if __name__ == "__main__":
    main()

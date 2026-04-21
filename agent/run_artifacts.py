"""Run artifact persistence — saves intermediate pipeline stage outputs to disk."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class RunArtifacts:
    """Persists intermediate pipeline stage outputs to a per-run directory."""

    def __init__(self, run_dir: Path, statement_path: str) -> None:
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self.save("meta.json", {"timestamp": run_dir.name, "statement_path": statement_path, "month": None})

    def save_meta(self, month: str) -> None:
        self.save("meta.json", {"timestamp": self.run_dir.name, "month": month})

    def save(self, filename: str, data: object) -> None:
        def _serialize(obj: object) -> object:
            if isinstance(obj, list):
                return [_serialize(item) for item in obj]
            if hasattr(obj, "model_dump"):
                return obj.model_dump(mode="json")
            return obj

        try:
            (self.run_dir / filename).write_text(
                json.dumps(_serialize(data), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("Failed to write artifact %s", filename, exc_info=True)

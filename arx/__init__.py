"""arx -- offline annual-report extraction with a confidence and audit layer.

Public entry points
-------------------
``arx.pipeline.run_batch``   -- process a folder of PDFs into a filled workbook.
``arx.run``                  -- the CLI wrapper around ``run_batch``.
``app.py``                   -- the Streamlit wrapper around ``run_batch``.

Everything tunable lives in the three YAML files next to this module; this
module owns loading them (once, cached) and nothing else.
"""

from __future__ import annotations

import logging
import random
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import yaml

from arx.models import BankingRule, InstitutionDef, MetricDef

__version__ = "1.0.0"

PKG_DIR = Path(__file__).resolve().parent

CONFIG_PATH = PKG_DIR / "config.yaml"
METRICS_PATH = PKG_DIR / "metrics.yaml"
INSTITUTIONS_PATH = PKG_DIR / "institutions.yaml"

log = logging.getLogger("arx")


def _read_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=8)
def load_config(path: str | None = None) -> Dict[str, Any]:
    """Load ``config.yaml`` (weights, penalties, thresholds, tolerances)."""
    return _read_yaml(Path(path) if path else CONFIG_PATH)


@lru_cache(maxsize=8)
def load_metrics(path: str | None = None) -> List[MetricDef]:
    """Load the metric dictionary, in template column order."""
    raw = _read_yaml(Path(path) if path else METRICS_PATH)
    metrics = [MetricDef(**m) for m in raw.get("metrics", [])]
    metrics.sort(key=lambda m: m.column)
    return metrics


@lru_cache(maxsize=8)
def load_banking_rules(path: str | None = None) -> List[BankingRule]:
    """Load the Level-2 banking-logic rules from ``metrics.yaml``."""
    raw = _read_yaml(Path(path) if path else METRICS_PATH)
    return [BankingRule(**r) for r in raw.get("banking_rules", [])]


@lru_cache(maxsize=8)
def load_institutions(path: str | None = None) -> List[InstitutionDef]:
    """Load the institution alias table."""
    raw = _read_yaml(Path(path) if path else INSTITUTIONS_PATH)
    return [InstitutionDef(**i) for i in raw.get("institutions", [])]


def metrics_by_key(path: str | None = None) -> Dict[str, MetricDef]:
    """``{metric_key: MetricDef}`` for O(1) lookup."""
    return {m.key: m for m in load_metrics(path)}


def seed_everything(seed: int | None = None) -> None:
    """Make the run deterministic: same input -> same output, every time."""
    if seed is None:
        seed = int(load_config()["runtime"]["random_seed"])
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))


def setup_logging(verbose: bool = False) -> None:
    """Structured logging for the CLI and the Streamlit app."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-14s %(message)s",
        datefmt="%H:%M:%S",
    )
    # These libraries are extremely chatty at DEBUG level.
    for noisy in ("pdfminer", "pdfplumber", "camelot", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


__all__ = [
    "load_config",
    "load_metrics",
    "load_banking_rules",
    "load_institutions",
    "metrics_by_key",
    "seed_everything",
    "setup_logging",
    "PKG_DIR",
    "__version__",
]

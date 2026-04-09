"""Caching utilities."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def load_or_compute(cache_path: str | Path, fn: Callable[[], T]) -> T:
    """Load a cached result or compute and cache it."""
    path = Path(cache_path)
    if path.exists():
        logger.info("Loading from cache: %s", path)
        with open(path, "rb") as f:
            return pickle.load(f)
    else:
        logger.info("Computing and caching to: %s", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        result = fn()
        with open(path, "wb") as f:
            pickle.dump(result, f)
        return result

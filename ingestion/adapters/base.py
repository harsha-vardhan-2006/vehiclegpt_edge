"""Adapter contract: every vehicle data source yields normalised records.

Maturity of each adapter is explicit so nothing simulated is presented as real.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator


@dataclass
class AdapterInfo:
    name: str
    input_format: str
    dependencies: str
    permissions: str
    implemented: bool
    test_status: str   # TESTED | NOT TESTED | NOT APPLICABLE
    limitations: str
    maturity: str      # simulated | replayed | real


class SourceAdapter(ABC):
    info: AdapterInfo

    @abstractmethod
    def read(self) -> Iterator[dict]:
        """Yield raw dicts: signal_name, timestamp, value, unit, trip_id (optional)."""
        raise NotImplementedError

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


JSONDict = Dict[str, Any]


@dataclass
class TopProcess:
    pid: Optional[int]
    name: Optional[str]
    value: Optional[float]
    unit: str

    def to_json(self) -> JSONDict:
        return {
            "pid": self.pid,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
        }

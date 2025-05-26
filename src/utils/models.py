from dataclasses import dataclass
from typing import Optional

@dataclass
class Pot:
    name: str
    initial: float = 0.0
    monthly: float = 0.0
    rate: float = 0.0
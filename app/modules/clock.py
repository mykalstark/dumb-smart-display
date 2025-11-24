from datetime import datetime
from typing import Dict, Optional


class Module:
    def __init__(self, config: Optional[Dict] = None) -> None:
        self.config = config or {}
        self.format = self.config.get("format", "%Y-%m-%d %H:%M:%S")
        self.title = self.config.get("title", "Clock")

    def render(self) -> str:
        now = datetime.now().strftime(self.format)
        return f"{self.title}\n{now}"

    def tick(self) -> None:
        # Clock does not need background work, but method reserved for parity.
        return None

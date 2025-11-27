# app/modules/clock.py
from datetime import datetime
from typing import Dict, Optional, Any


class Module:
    # Accept fonts (even if we don't use them yet) to prevent errors
    def __init__(self, config: Optional[Dict] = None, fonts: Optional[Dict] = None) -> None:
        self.config = config or {}
        self.format = self.config.get("format", "%Y-%m-%d %H:%M:%S")
        self.title = self.config.get("title", "Clock")

    # Accept **kwargs to safely ignore 'width' and 'height' if we don't need them
    def render(self, **kwargs) -> str:
        now = datetime.now().strftime(self.format)
        return f"{self.title}\n{now}"

    def tick(self) -> None:
        return None
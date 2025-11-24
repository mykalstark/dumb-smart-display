import os
from datetime import datetime
from typing import Optional

BTN1 = 17
BTN2 = 27
BTN3 = 22


def log(msg: str) -> None:
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[BUTTONS] [{t}] {msg}", flush=True)


def _import_button():
    try:
        from gpiozero import Button  # type: ignore

        return Button
    except Exception as exc:  # pragma: no cover - import-time failures logged
        log(f"gpiozero unavailable ({exc}). Falling back to simulation mode.")
        return None


def init_buttons(display: Optional[object] = None, simulate: bool = False) -> None:
    simulate = simulate or os.environ.get("DISPLAY_SIMULATE", "").lower() in {"1", "true", "yes"}

    if simulate:
        log("Simulation enabled: skipping hardware button setup.")
        return

    Button = _import_button()
    if Button is None:
        return

    b1 = Button(BTN1, pull_up=True, bounce_time=0.05)
    b2 = Button(BTN2, pull_up=True, bounce_time=0.05)
    b3 = Button(BTN3, pull_up=True, bounce_time=0.05)

    b1.when_pressed = lambda: log("Button 1 pressed")
    b2.when_pressed = lambda: log("Button 2 pressed")
    b3.when_pressed = lambda: log("Button 3 pressed")

    log("Buttons initialized.")

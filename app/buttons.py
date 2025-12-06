import os
from datetime import datetime
from typing import Callable, Optional

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


# Hold references to button objects so they are not garbage collected
_BUTTONS = []


def init_buttons(
    display: Optional[object] = None,
    simulate: bool = False,
    on_event: Optional[Callable[[str], None]] = None,
) -> None:
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

    def _dispatch(event: str) -> None:
        log(f"Button event: {event}")
        if on_event:
            on_event(event)

    # Physical layout (left-to-right): back, refresh, next
    b1.when_pressed = lambda: _dispatch("back")
    b2.when_pressed = lambda: _dispatch("refresh")
    b3.when_pressed = lambda: _dispatch("next")

    # Store references to prevent garbage collection, which would drop callbacks
    global _BUTTONS
    _BUTTONS = [b1, b2, b3]

    log("Buttons initialized.")

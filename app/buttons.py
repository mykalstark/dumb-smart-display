import os
from datetime import datetime
from typing import Callable, Optional

BTN1 = 17
BTN2 = 27
BTN3 = 22
HOLD_SECONDS = 1.0


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

    b1 = Button(BTN1, pull_up=True, bounce_time=0.05, hold_time=HOLD_SECONDS)
    b2 = Button(BTN2, pull_up=True, bounce_time=0.05)
    b3 = Button(BTN3, pull_up=True, bounce_time=0.05, hold_time=HOLD_SECONDS)

    def _dispatch(event: str) -> None:
        log(f"Button event: {event}")
        if on_event:
            on_event(event)

    def _navigation_button(button, tap_event: str, hold_event: str) -> None:
        held = False

        def pressed() -> None:
            nonlocal held
            held = False

        def on_hold() -> None:
            nonlocal held
            held = True
            _dispatch(hold_event)

        def released() -> None:
            # Defer taps until release so a hold never pages before switching.
            if not held:
                _dispatch(tap_event)

        button.when_pressed = pressed
        button.when_held = on_hold
        button.when_released = released

    # Taps page within RSS/Countdown; holds always switch modules.
    _navigation_button(b1, "back", "module_back")
    b2.when_pressed = lambda: _dispatch("refresh")
    _navigation_button(b3, "next", "module_next")

    # Store references to prevent garbage collection, which would drop callbacks
    global _BUTTONS
    _BUTTONS = [b1, b2, b3]

    log("Buttons initialized.")

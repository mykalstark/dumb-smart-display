#!/usr/bin/env python3

from app.buttons import init_buttons
from app.display import Display
import time
from datetime import datetime

def main():
    display = Display(simulate=True)
    init_buttons(display)

    print("[MAIN] Dumb Smart Display starting...", flush=True)

    try:
        while True:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            display.render_text(f"Dumb Smart Display\n{now}")
            time.sleep(30)
    except KeyboardInterrupt:
        print("[MAIN] Exiting...")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import sys
import time
from PIL import Image, ImageDraw, ImageFont

# -----------------------------------------------------------------------------
# Make sure Python can find ./lib/waveshare_epd
# -----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.append(LIB_DIR)

# -----------------------------------------------------------------------------
# Import epdconfig FIRST and patch pins BEFORE importing the panel driver.
# This avoids the default GPIO17 reset conflict with your Button 1.
# -----------------------------------------------------------------------------
import waveshare_epd.epdconfig as epdconfig

# Your wiring:
#   RST  -> GPIO5   (Pin 29)
#   DC   -> GPIO25  (Pin 22)
#   BUSY -> GPIO24  (Pin 18)
#   CS   -> GPIO8   (Pin 24, CE0)
#   MOSI -> GPIO10  (Pin 19)
#   SCLK -> GPIO11  (Pin 23)
#   VCC / PWR -> 3.3V (Pins 1 and 17)
#   GND -> Pin 39
print("Patching epdconfig GPIO pin assignments (before driver import)...")
epdconfig.RST_PIN = 5      # Reset
epdconfig.DC_PIN = 25      # Data/Command
epdconfig.BUSY_PIN = 24    # Busy
epdconfig.CS_PIN = 8       # Chip Select (CE0)
epdconfig.MOSI_PIN = 10    # SPI0 MOSI
epdconfig.SCLK_PIN = 11    # SPI0 SCLK
print(
    f"  RST_PIN={epdconfig.RST_PIN}, DC_PIN={epdconfig.DC_PIN}, "
    f"BUSY_PIN={epdconfig.BUSY_PIN}, CS_PIN={epdconfig.CS_PIN}, "
    f"MOSI_PIN={epdconfig.MOSI_PIN}, SCLK_PIN={epdconfig.SCLK_PIN}"
)

# -----------------------------------------------------------------------------
# Now import the driver. It will see ONLY the patched pins above.
# For 7.5\" V2 black/white, use epd7in5_V2.
# For 7.5\" V2 3-color (B/W/Red), you would use epd7in5b_V2 instead.
# -----------------------------------------------------------------------------
from waveshare_epd import epd7in5_V2


def clear_display(epd):
    """
    Handle both Clear() and Clear(color) styles.
    The 7.5\" V2 uses Clear() with no arguments.
    """
    try:
        epd.Clear(0xFF)
    except TypeError:
        epd.Clear()


def full_image(epd, value: int):
    """
    Draw a full-frame image filled with 'value':
      0   = all black
      255 = all white
    """
    image = Image.new("1", (epd.width, epd.height), value)
    epd.display(epd.getbuffer(image))


def main():
    print("Initializing 7.5\" V2 e-ink display...")

    try:
        print("Creating EPD instance...")
        epd = epd7in5_V2.EPD()
        print("EPD instance created.")

        print("Calling epd.init() ... (this can take a couple of seconds)")
        epd.init()
        print("epd.init() done.")

        print("Clearing display to white (driver Clear)...")
        clear_display(epd)
        print("Driver clear complete. Waiting 3 seconds...")
        time.sleep(3)

        print(f"EPD width={epd.width}, height={epd.height}")

        # Force full white and full black frames to make activity obvious
        print("Forcing FULL WHITE frame...")
        full_image(epd, 255)
        print("Full white sent. Waiting 5 seconds...")
        time.sleep(5)

        print("Forcing FULL BLACK frame...")
        full_image(epd, 0)
        print("Full black sent. Waiting 5 seconds...")
        time.sleep(5)

        # Draw test text
        print("Drawing test text image...")
        image = Image.new("1", (epd.width, epd.height), 255)
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28
            )
        except Exception:
            font = ImageFont.load_default()

        text_lines = [
            "Dumb Smart Display",
            "7.5\" V2 panel test",
            "Hello, Mykal 👋",
        ]

        y = 40
        for line in text_lines:
            draw.text((40, y), line, font=font, fill=0)
            y += 50

        epd.display(epd.getbuffer(image))
        print("Text image pushed to display. Waiting 5 seconds...")
        time.sleep(5)

        print("Putting display to sleep...")
        epd.sleep()
        print("EPD put to sleep. Done.")

    except KeyboardInterrupt:
        print("Interrupted by user, cleaning up GPIO...")
        try:
            epdconfig.module_exit()
        except Exception:
            pass
    except Exception as e:
        print(f"ERROR: {e}")
        try:
            epdconfig.module_exit()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
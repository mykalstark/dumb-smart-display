from gpiozero import Button
from datetime import datetime

BTN1 = 17
BTN2 = 27
BTN3 = 22

def log(msg):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[BUTTONS] [{t}] {msg}", flush=True)

def init_buttons(display):
    b1 = Button(BTN1, pull_up=True, bounce_time=0.05)
    b2 = Button(BTN2, pull_up=True, bounce_time=0.05)
    b3 = Button(BTN3, pull_up=True, bounce_time=0.05)

    b1.when_pressed = lambda: log("Button 1 pressed")
    b2.when_pressed = lambda: log("Button 2 pressed")
    b3.when_pressed = lambda: log("Button 3 pressed")

    log("Buttons initialized.")

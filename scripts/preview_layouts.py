"""Render every display screen with offline sample data for visual review.

Run: python -m scripts.preview_layouts --output /tmp/display-layouts
No configured services or credentials are used.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.display import Display
from app.modules import (
    calendar_ics, clock, countdown, mealie_today, rss_feed,
    spotify_now_playing, system_status, ticktick, weather_forecast,
)
from app.modules.ticktick_client import TaskItem


def sample_fonts():
    try:
        return {
            "default": ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24),
            "small": ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18),
            "large": ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48),
        }
    except OSError:
        font = ImageFont.load_default()
        return dict(default=font, small=font, large=font)


def build_samples(state="normal", fonts=None):
    """Return modules with populated caches, including edge and idle states."""
    fonts = fonts or sample_fonts()
    now, today = datetime.now(), date.today()
    long = "Wednesday's exceptionally long title with WWWWWW and international café details " * 4
    modules = []
    home = clock.Module({"location_name": long if state == "long" else "Home"}, fonts)
    home.weather = dict(current=72, high=81, low=59)
    home.last_weather_fetch = now
    modules.append(home)

    dinner = mealie_today.Module({}, fonts)
    dinner.meal_details = dict(name=long if state == "long" else "Lemon Chicken & Roasted Vegetables",
                               prep=20, cook=45, total=65)
    modules.append(dinner)

    tasks = ticktick.Module({}, fonts)
    tasks.last_fetch = now.replace(tzinfo=tasks.timezone)
    tasks.today_tasks = [TaskItem(long if state == "long" else title, "Home", today,
                                 time(9 + i, 30), False, False)
                         for i, title in enumerate(("Pick up groceries", "Water the garden", "Plan the weekend"))]
    tasks.tomorrow_tasks = [TaskItem("Book dentist appointment", "Personal", today + timedelta(days=1),
                                    None, True, False)]
    if state == "long":
        tasks.today_tasks *= 3
        tasks.today_overflow = 12
    modules.append(tasks)

    calendar = calendar_ics.Module({}, fonts)
    calendar._last_fetch = calendar._last_updated = now
    calendar._today_events = [calendar_ics._Event(long if state == "long" else title, today,
                                                time(10 + i, 0), False)
                              for i, title in enumerate(("Team catch-up", "Lunch with Alex", "Walk in the park"))]
    calendar._tomorrow_events = [calendar_ics._Event("Family dinner", today + timedelta(days=1), time(18, 30), False)]
    if state == "long":
        calendar._today_events *= 5
    modules.append(calendar)

    news = rss_feed.Module({}, fonts)
    news._last_fetch = news._last_updated = now
    news._feed_title = long if state == "long" else "Good News"
    news._items = [{"title": long if state == "long" else title} for title in (
        "Community garden brings neighbors together",
        "Local library opens a new reading room",
        "Volunteers restore a favorite walking trail",
        "Students build a solar-powered science project",
        "New rescue center welcomes its first animals",
        "Weekend market celebrates local makers",
        "Young musicians perform for the community",
        "Town celebrates a record year of recycling")]
    modules.append(news)

    count = countdown.Module({"events": [
        {"name": long if state == "long" else "Family Vacation", "date": (today + timedelta(days=42)).isoformat()},
        {"name": "Birthday", "date": (today + timedelta(days=80)).isoformat()},
    ]}, fonts)
    modules.append(count)

    music = spotify_now_playing.Module({}, fonts)
    music._last_fetch = music._last_updated = now
    music._track = long if state == "long" else "Here Comes the Sun"
    music._artist = long if state == "long" else "The Beatles"
    music._album = long if state == "long" else "Abbey Road"
    music._is_playing = True
    modules.append(music)

    status = system_status.Module({}, fonts)
    status._last_fetch = now
    status._stats = dict(cpu_temp=82.5, cpu_pct=18, ram_used=1.2e9, ram_total=4e9,
                         disk_used=12e9, disk_total=32e9, uptime="3d 12h", ip="192.168.1.42")
    if state == "long":
        status._stats.update(uptime="9999d 23h 59m", ip="255.255.255.255")
    modules.append(status)

    forecast = weather_forecast.Module({}, fonts)
    forecast._last_fetch = now
    forecast._days = [dict(dt=now + timedelta(days=i), day=(now + timedelta(days=i)).strftime("%a"),
                           icon=icon, high=81 - i, low=59 - i, precip=0.1 if i > 2 else 0)
                       for i, icon in enumerate(("sun", "sun_cloud", "cloud", "rain", "drizzle", "snow", "storm"))]
    modules.append(forecast)

    if state in ("empty", "error"):
        home.weather = dict(current=None, high=None, low=None)
        home.last_weather_fetch = None
        dinner.meal_details = dict(name=None, prep=None, cook=None, total=None)
        tasks.today_tasks = tasks.tomorrow_tasks = []
        tasks.today_overflow = tasks.tomorrow_overflow = 0
        calendar._today_events = calendar._tomorrow_events = []
        news._items = []
        count._events = []
        music._track = None
        forecast._days = []
    if state == "error":
        tasks.error_message = long
        calendar._error = news._error = music._error = forecast._error = long
        status._stats = {}
    return modules


class CapturingDriver:
    def render_image(self, image, force_full_refresh=False):
        self.image = image


def render_gallery(output, width=800, height=480):
    output.mkdir(parents=True, exist_ok=True)
    driver = CapturingDriver()
    display = Display(driver=driver)
    sections, normal_images = [], []
    for state in ("normal", "long", "empty", "error"):
        figures = []
        for module in build_samples(state):
            layouts = ["full"]
            if state in ("normal", "long") and module.name in ("clock", "mealie_today"):
                layouts += [layout.name for layout in module.supported_layouts() if layout.name != "full"]
            for layout in layouts:
                display.render(module.render(width, height, layout=layout))
                filename = f"{module.name}-{layout}-{state}.png"
                driver.image.save(output / filename)
                label = f"{module.name} · {layout} · {state}"
                figures.append(f'<figure><figcaption>{escape(label)}</figcaption><img src="{filename}"></figure>')
                if state == "normal" and layout == "full":
                    normal_images.append((module.name, driver.image.copy()))
        sections.append(f'<h2>{state.title()}</h2><div class="grid">{"".join(figures)}</div>')
    from app.main import _render_after_hours

    driver.width, driver.height = width, height
    display.render_text("Starting display…")
    driver.image.save(output / 'startup.png')
    _render_after_hours(display, {}, sample_fonts())
    driver.image.save(output / 'after-hours.png')
    sections.append('<h2>Fallback messages</h2><div class="grid">'
                    '<figure><figcaption>Startup</figcaption><img src="startup.png"></figure>'
                    '<figure><figcaption>After hours without a photo</figcaption><img src="after-hours.png"></figure></div>')
    html = '<!doctype html><meta charset="utf-8"><title>Display layout review</title>'
    html += '<style>body{font:16px system-ui;background:#eee;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}figure{margin:0}img{width:100%;height:auto}figcaption{margin-bottom:8px}</style>'
    html += '<h1>Display layout review · offline sample data</h1>' + ''.join(sections)
    (output / 'index.html').write_text(html)
    scale = min(1, 400 / width)
    tw, th = round(width * scale), round(height * scale)
    montage = Image.new('RGB', (3 * (tw + 16) + 16, 3 * (th + 40) + 16), 'white')
    draw = ImageDraw.Draw(montage)
    for i, (name, image) in enumerate(normal_images):
        x, y = 16 + (i % 3) * (tw + 16), 16 + (i // 3) * (th + 40)
        draw.text((x, y), name, fill='black')
        montage.paste(image.convert('RGB').resize((tw, th)), (x, y + 20))
    montage.save(output / 'overview.png')
    print(output / 'index.html')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/display-layouts'))
    parser.add_argument('--width', type=int, default=800)
    parser.add_argument('--height', type=int, default=480)
    args = parser.parse_args()
    render_gallery(args.output, args.width, args.height)

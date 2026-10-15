"""Build a small animated SVG from GitHub's public contribution calendar.

Uses only the Python standard library. Fails on missing/changed calendar data
instead of replacing the existing assets with invented or zero-filled activity.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from html import escape
from html.parser import HTMLParser
import math
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


class CalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: dict[str, tuple[date, int]] = {}
        self.counts: dict[str, int] = {}
        self.tooltip_id: str | None = None
        self.tooltip_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if attr.get("data-date") and attr.get("id") and "data-level" in attr:
            self.cells[str(attr["id"])] = (
                date.fromisoformat(str(attr["data-date"])),
                int(str(attr["data-level"])),
            )
        if tag == "tool-tip" and attr.get("for"):
            self.tooltip_id = str(attr["for"])
            self.tooltip_text = []

    def handle_data(self, data: str) -> None:
        if self.tooltip_id is not None:
            self.tooltip_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "tool-tip" or self.tooltip_id is None:
            return
        text = " ".join("".join(self.tooltip_text).split())
        match = re.match(r"([\d,]+) contributions?\b", text, re.I)
        if match:
            self.counts[self.tooltip_id] = int(match.group(1).replace(",", ""))
        elif re.match(r"No contributions\b", text, re.I):
            self.counts[self.tooltip_id] = 0
        self.tooltip_id = None
        self.tooltip_text = []


def parse_calendar(source: str) -> list[tuple[date, int]]:
    parser = CalendarParser()
    parser.feed(source)
    if len(parser.cells) < 350:
        raise ValueError("A complete GitHub calendar was not returned; existing artwork is unchanged.")
    result: dict[date, int] = {}
    for cell_id, (day, _level) in parser.cells.items():
        if cell_id not in parser.counts:
            raise ValueError(f"Contribution count missing for {day}; existing artwork is unchanged.")
        result[day] = parser.counts[cell_id]
    days = sorted(result)
    if len(days) < 350 or any(b - a != timedelta(days=1) for a, b in zip(days, days[1:])):
        raise ValueError("Contribution dates are incomplete; existing artwork is unchanged.")
    return [(day, result[day]) for day in days]


def weekly_activity(days: list[tuple[date, int]]) -> list[tuple[date, int]]:
    last_day = days[-1][0]
    last_sunday = last_day - timedelta(days=(last_day.weekday() + 1) % 7)
    first_sunday = last_sunday - timedelta(weeks=51)
    weeks = [(first_sunday + timedelta(weeks=i), 0) for i in range(52)]
    totals = [0] * 52
    for day, count in days:
        index = (day - first_sunday).days // 7
        if 0 <= index < 52:
            totals[index] += count
    return [(start, totals[i]) for i, (start, _) in enumerate(weeks)]


def fetch_calendar(username: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username):
        raise ValueError("Invalid GitHub username.")
    request = Request(
        f"https://github.com/users/{username}/contributions",
        headers={"User-Agent": "MeetProfileActivity/1.0", "Accept-Language": "en-US,en;q=0.9"},
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Calendar unavailable.")


def render(weeks: list[tuple[date, int]], username: str, theme: str) -> str:
    colors = {
        "dark": {"bg": "#0d1117", "edge": "#26323b", "text": "#e6edf3", "muted": "#8b9aa7",
                 "grid": "#1c2831", "empty": "#202d34", "bar": "#387e73", "line": "#65c7b1", "dot": "#a6f3db"},
        "light": {"bg": "#ffffff", "edge": "#dce5e3", "text": "#182b2a", "muted": "#667b78",
                  "grid": "#edf2f0", "empty": "#e6eeeb", "bar": "#69a99b", "line": "#398773", "dot": "#146c55"},
    }[theme]
    left, right, baseline = 28.0, 852.0, 177.0
    step = (right - left) / 52
    maximum = max(count for _, count in weeks)
    total = sum(count for _, count in weeks)
    bars: list[str] = []
    points: list[tuple[float, float]] = []
    for index, (start, count) in enumerate(weeks):
        height = 3 if count == 0 else 10 + 60 * math.log1p(count) / math.log1p(maximum)
        x, y = left + index * step, baseline - height
        color = colors["empty"] if count == 0 else colors["bar"]
        bars.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="9" height="{height:.2f}" rx="3" fill="{color}"><title>Week of {start.isoformat()}: {count} contributions</title></rect>')
        points.append((x + 4.5, y - 7))
    path = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    last_x, last_y = points[-1]
    first_month, last_month = weeks[0][0].strftime("%b %Y"), weeks[-1][0].strftime("%b %Y")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="880" height="232" viewBox="0 0 880 232" role="img" aria-labelledby="title desc">
  <title id="title">{escape(username)} — activity signal</title>
  <desc id="desc">{total:,} contributions across 52 calendar weeks, including the current partial week. Each bar represents one week. A small light follows the weekly pattern.</desc>
  <style>
    text {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }}
    .mono {{ font-family: ui-monospace, 'SFMono-Regular', Consolas, monospace; }}
    .still {{ display: none; }}
    @media (prefers-reduced-motion: reduce) {{ .moving {{ display: none; }} .still {{ display: inline; }} }}
  </style>
  <rect x="0.5" y="0.5" width="879" height="231" rx="14" fill="{colors['bg']}" stroke="{colors['edge']}"/>
  <text x="28" y="35" font-size="13" font-weight="600" fill="{colors['text']}">Activity signal</text>
  <text x="852" y="35" text-anchor="end" class="mono" font-size="10" letter-spacing="1.2" fill="{colors['muted']}">52 WEEKS</text>
  <text x="28" y="57" font-size="11" fill="{colors['muted']}">{total:,} contributions · one bar per week</text>
  <path d="M28 100H852 M28 139H852 M28 183H852" fill="none" stroke="{colors['grid']}" stroke-width="1"/>
  {''.join(bars)}
  <path d="{path}" fill="none" stroke="{colors['line']}" stroke-width="1.4" stroke-linejoin="round" opacity="0.36"/>
  <g class="moving">
    <circle r="8" fill="{colors['dot']}" opacity="0.10"/>
    <circle r="3" fill="{colors['dot']}"/>
    <animateMotion dur="28s" repeatCount="indefinite" calcMode="paced" path="{path}"/>
  </g>
  <circle class="still" cx="{last_x:.2f}" cy="{last_y:.2f}" r="3" fill="{colors['dot']}"/>
  <text x="28" y="211" class="mono" font-size="10" fill="{colors['muted']}">{first_month}</text>
  <text x="852" y="211" text-anchor="end" class="mono" font-size="10" fill="{colors['muted']}">{last_month}</text>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="07MEET")
    parser.add_argument("--calendar", type=Path, help="Use a previously downloaded calendar (offline preview).")
    parser.add_argument("--output", type=Path, default=ROOT / "assets")
    args = parser.parse_args()
    source = args.calendar.read_text(encoding="utf-8") if args.calendar else fetch_calendar(args.username)
    days = parse_calendar(source)
    weeks = weekly_activity(days)
    artwork = {theme: render(weeks, args.username, theme) for theme in ("dark", "light")}
    args.output.mkdir(parents=True, exist_ok=True)
    for theme, svg in artwork.items():
        destination = args.output / f"activity-{theme}.svg"
        temporary = destination.with_suffix(".svg.tmp")
        temporary.write_text(svg, encoding="utf-8")
        temporary.replace(destination)
    print(f"Generated both themes from {len(days)} real calendar days ending {days[-1][0]}.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, HTTPError, URLError, TimeoutError) as error:
        print(f"Activity update failed: {error}", file=sys.stderr)
        sys.exit(1)

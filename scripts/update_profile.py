"""Draw GitHub's public activity as self-contained, static SVG artwork."""

import calendar
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
import os
from pathlib import Path
import random
import re
import subprocess
import time
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
ACCENT_LIGHT = "#2d7a4c"  # Crisp botanical emerald (high contrast in light mode)
ACCENT_DARK = "#4ade80"   # Luminous mint emerald (pops cleanly in dark mode)
DIVIDER_LIGHT = "#d0dbcd" # Subtle line divider
DIVIDER_DARK = "#263628"  # Subtle dark line divider

PAPER, INK, MUTED = "#faf8f2", "#343c36", "#72766a"
COLORS = ["#e8ede7", "#a3e6a9", "#48c769", "#2e9e4f", "#1c6d35"]
COLORS_DARK = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]

LANG_PALETTE_LIGHT = ["#2d7a4c", "#3d8f5b", "#5aa873", "#7ec092", "#2c8f85", "#a5c4ad"]
LANG_PALETTE_DARK = ["#4ade80", "#26a641", "#56d364", "#7ee787", "#4ec9b0", "#8bc49f"]


def gh(*args, retries=3, delay=2):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                ["gh", "api", *args],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            data = json.loads(result.stdout)
            if isinstance(data, dict) and data.get("errors"):
                raise RuntimeError(f"GitHub GraphQL failed: {data['errors']}")
            return data
        except subprocess.CalledProcessError as exc:
            last_err = exc
            err_msg = exc.stderr.strip() if exc.stderr else "unknown error"
            print(f"Warning: gh api attempt {attempt}/{retries} failed: {err_msg}", flush=True)
            if attempt < retries:
                time.sleep(delay * attempt)
        except Exception as exc:
            last_err = exc
            print(f"Warning: gh attempt {attempt}/{retries} failed: {exc}", flush=True)
            if attempt < retries:
                time.sleep(delay * attempt)
    if isinstance(last_err, subprocess.CalledProcessError):
        stderr_msg = last_err.stderr.strip() if last_err.stderr else "no stderr output"
        raise RuntimeError(f"gh api failed after {retries} attempts: {stderr_msg}") from last_err
    raise last_err


def contributions(username, start, end):
    query = """query($user: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $user) { contributionsCollection(from: $from, to: $to) {
        contributionCalendar { weeks { contributionDays {
          date contributionCount contributionLevel
        } } }
      } }
    }"""
    data = gh("graphql", "-f", f"query={query}", "-f", f"user={username}",
              "-f", f"from={start}", "-f", f"to={end}")
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [day for week in weeks for day in week["contributionDays"]]


def streak(days, today):
    """Allow today to be unfinished; a missing calendar day breaks a streak."""
    counts = {date.fromisoformat(d["date"]): d["contributionCount"] for d in days}
    cursor = today if counts.get(today, 0) else today - timedelta(days=1)
    total = 0
    while counts.get(cursor, 0):
        total += 1
        cursor -= timedelta(days=1)
    return total


def parse_views(svg):
    root = ET.fromstring(svg)
    label = root.attrib.get("aria-label", "")
    match = re.search(r"Profile views:\s*([\d,]+)\s*$", label, re.I)
    if not match:
        values = [t.text.strip() for t in root.iter("{http://www.w3.org/2000/svg}text")
                  if t.text and re.fullmatch(r"[\d,]+", t.text.strip())]
        if not values:
            raise ValueError("Profile counter returned no numeric count")
        return int(values[-1].replace(",", ""))
    return int(match[1].replace(",", ""))


def profile_views(username):
    # The service increments only github-camo requests. This fetch is read-only.
    request = Request(f"https://komarev.com/ghpvc/?username={username}",
                      headers={"User-Agent": "profile-artwork/1.0"})
    with urlopen(request, timeout=30) as response:
        return parse_views(response.read())


class Drawing:
    def __init__(self, height, title, description, width=760):
        self.font = TTFont(ROOT / "assets/fonts/Caveat.ttf")
        self.glyphs = self.font.getGlyphSet(location={"wght": 500})
        self.cmap = self.font.getBestCmap()
        self.units = self.font["head"].unitsPerEm
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                      f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title>',
                      f'<desc id="desc">{escape(description)}</desc>',
                      '<!-- Transparent canvas integrates with the GitHub theme. -->']

    def text(self, value, x, y, size, color=INK, center=False):
        value = str(value)
        scale = size / self.units
        names = [self.cmap[ord(c)] for c in value]
        width = sum(self.glyphs[n].width for n in names) * scale
        if center:
            x -= width / 2
        self.parts.append(f'<g fill="{color}" aria-label="{escape(value, quote=True)}">')
        for name in names:
            pen = SVGPathPen(self.glyphs)
            self.glyphs[name].draw(pen)
            path = pen.getCommands()
            if path:
                self.parts.append(f'<path transform="translate({x:.3f} {y}) scale({scale:.5f} {-scale:.5f})" d="{path}"/>')
            x += self.glyphs[name].width * scale
        self.parts.append('</g>')

    def circle(self, cx, cy, r, color=MUTED, width=1):
        self.parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{width}"/>')

    def line(self, path, color=MUTED, width=1):
        self.parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>')

    def wrap(self, value, size, width):
        lines, line = [], ""
        for word in value.split():
            candidate = f"{line} {word}".strip()
            measured = sum(self.glyphs[self.cmap[ord(c)]].width for c in candidate) * size / self.units
            if line and measured > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        return lines + [line] if line else lines

    def save(self, path):
        svg = "\n".join(self.parts + ["</svg>"]) + "\n"
        path.write_text(svg, encoding="utf-8")
        dark_colors = {
            INK: "#e6edf3",
            MUTED: "#a4afa5",
            ACCENT_LIGHT: ACCENT_DARK,
            DIVIDER_LIGHT: DIVIDER_DARK,
            "#dadcd0": DIVIDER_DARK,
            "#d7ddcd": DIVIDER_DARK,
            "#e5e7dd": "#212824",
            "#9da98a": ACCENT_DARK,
            "#65805e": LANG_PALETTE_DARK[0],
        }
        for cl, cd in zip(COLORS, COLORS_DARK):
            dark_colors[cl] = cd
        for cl, cd in zip(LANG_PALETTE_LIGHT, LANG_PALETTE_DARK):
            dark_colors[cl] = cd
        dark = re.sub(r"#[0-9a-fA-F]{6}", lambda match: dark_colors.get(match[0], match[0]), svg)
        path.with_name(path.stem + "-dark.svg").write_text(dark, encoding="utf-8")


def draw_name(name):
    art = Drawing(120, name, "A handwritten signature with a detailed X-wing starfighter sketch in attack position among stars.")
    art.text(name, 6, 78, 76)
    art.line("M 10,91 Q 140,96 302,88", ACCENT_LIGHT, 2)
    # Master Front-View X-wing in Attack Position (Lock S-Foils)
    # Central fuselage & nose cone
    art.line("M 677,48 L 672,59 L 670,72 L 677,85 L 684,72 L 682,59 Z", ACCENT_LIGHT, 1.5)
    art.line("M 677,61 L 677,85", ACCENT_LIGHT, 0.8)
    # Cockpit canopy & glass framing
    art.line("M 673,63 L 681,63 L 679,72 L 675,72 Z", ACCENT_LIGHT, 1.2)
    art.line("M 677,63 L 677,72", ACCENT_LIGHT, 0.8)
    art.line("M 674,67 L 680,67", ACCENT_LIGHT, 0.7)
    # Astromech droid R2 unit dome
    art.line("M 674,56 A 3,3 0 0,1 680,56 Z", ACCENT_LIGHT, 1.1)

    # 4 Engine Intakes (circular turbine nacelles at wing roots)
    for cx, cy in [(663, 58), (663, 74), (691, 58), (691, 74)]:
        art.circle(cx, cy, 4.5, ACCENT_LIGHT, 1.3)
        art.circle(cx, cy, 1.8, ACCENT_LIGHT, 0.8)

    # 4 S-Foil Wings in Attack Position (aerodynamic foil double lines)
    # Upper Left
    art.line("M 658,55 L 620,34 L 622,40 L 659,59", ACCENT_LIGHT, 1.4)
    art.line("M 640,45 L 642,48", ACCENT_LIGHT, 0.8)
    # Lower Left
    art.line("M 658,77 L 620,98 L 622,92 L 659,73", ACCENT_LIGHT, 1.4)
    art.line("M 640,87 L 642,84", ACCENT_LIGHT, 0.8)
    # Upper Right
    art.line("M 696,55 L 734,34 L 732,40 L 695,59", ACCENT_LIGHT, 1.4)
    art.line("M 714,45 L 712,48", ACCENT_LIGHT, 0.8)
    # Lower Right
    art.line("M 696,77 L 734,98 L 732,92 L 695,73", ACCENT_LIGHT, 1.4)
    art.line("M 714,87 L 712,84", ACCENT_LIGHT, 0.8)

    # 4 Wingtip Laser Cannons with Cooling Coils & Muzzle Flares
    # Upper Left Cannon
    art.line("M 620,23 L 620,45 M 617,25 L 623,25 M 618,28 L 622,28 M 618,31 L 622,31", ACCENT_LIGHT, 1.3)
    # Lower Left Cannon
    art.line("M 620,87 L 620,109 M 617,107 L 623,107 M 618,104 L 622,104 M 618,101 L 622,101", ACCENT_LIGHT, 1.3)
    # Upper Right Cannon
    art.line("M 734,23 L 734,45 M 731,25 L 737,25 M 732,28 L 736,28 M 732,31 L 736,31", ACCENT_LIGHT, 1.3)
    # Lower Right Cannon
    art.line("M 734,87 L 734,109 M 731,107 L 737,107 M 732,104 L 736,104 M 732,101 L 736,101", ACCENT_LIGHT, 1.3)

    # Starfield
    for x, y in [(596, 50), (755, 56), (604, 88), (748, 84)]:
        art.line(f"M {x-3},{y} L {x+3},{y} M {x},{y-3} L {x},{y+3}", MUTED, 0.8)
    art.save(ROOT / "assets/name.svg")


def draw_content():
    blocks = [
        ("about", "Mechanical engineering student / France", [
            "I'm not a developer; I love coding in my free time, especially where software, hardware, and music meet. Still a Padawan, always learning.",
            "I write my contributions to other people's repositories myself. Some of my personal projects are vibe-coded with AI, including OSCMidi."], None),
        ("project-osc", "OSCMidi", [
            "A Windows bridge for RTP-MIDI, local MIDI, OSC, and VST instruments."],
            "Rust / TypeScript / Tauri / Vibe-coded with AI"),
        ("project-piano", "Piano LED Visualizer", [
            "Connect an LED strip to a Raspberry Pi for an immersive visual experience on piano.",
            "Custom fork optimized for the Raspberry Pi Zero 2 W."],
            "Python / Raspberry Pi Zero 2 W / Optimized fork"),
    ]
    for filename, title, paragraphs, note in blocks:
        for mobile in [False, True]:
            width, pad, body, heading = (380, 12, 24, 30) if mobile else (760, 36, 28, 34)
            art = Drawing(1, title, " ".join([title, *paragraphs, note or ""]), width)
            y = 35
            for line in art.wrap(title, heading, width - 2 * pad):
                art.text(line, pad, y, heading)
                y += heading * 1.15
            y -= heading * 1.15
            for index, paragraph in enumerate(paragraphs):
                y += 38 if index == 0 else 18
                for line in art.wrap(paragraph, body, width - 2 * pad):
                    art.text(line, pad, y, body)
                    y += body * 1.3
            if note:
                y += 6
                for line in art.wrap(note, body - 3, width - 2 * pad):
                    art.text(line, pad, y, body - 3, MUTED)
                    y += body * 1.2
            height = round(y - body * (1.2 if note else 1.3) + 22)
            art.parts[0] = art.parts[0].replace('height="1"', f'height="{height}"').replace(f'viewBox="0 0 {width} 1"', f'viewBox="0 0 {width} {height}"')
            art.save(ROOT / f'assets/{filename}{"-mobile" if mobile else ""}.svg')
    for filename, title in [("heading-projects", "Selected projects"), ("heading-tools", "My tools")]:
        for mobile in [False, True]:
            art = Drawing(64, title, title, 380 if mobile else 760)
            art.text(title, 12 if mobile else 36, 43, 30 if mobile else 34)
            art.line("M 220,34 L 368,34" if mobile else "M 300,34 Q 490,32 723,34", DIVIDER_LIGHT)
            art.save(ROOT / f'assets/{filename}{"-mobile" if mobile else ""}.svg')
    for filename, title, width in [("link-downloads", "Releases & downloads", 242),
                                    ("link-fork", "Piano LED Visualizer fork", 262),
                                    ("link-repos", "All repositories", 187),
                                    ("link-prs", "My pull requests", 192)]:
        art = Drawing(38, title, title, width)
        art.text(title, 36, 26, 25)
        art.line(f"M 37,32 Q {width//2},34 {width-12},31", ACCENT_LIGHT)
        art.save(ROOT / f"assets/{filename}.svg")


def language_totals(repos, username):
    projects = [repo for repo in repos if not repo["fork"]
                and repo["name"].lower() != username.lower()]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda repo: gh(f'repos/{repo["full_name"]}/languages'), projects)
        totals = Counter()
        for languages in results:
            totals.update(languages)
    return totals, len(projects)


def language_shares(totals):
    """Group small languages and apportion tenths so the displayed sum is 100%."""
    ordered = sorted(((name, size) for name, size in totals.items() if size > 0),
                     key=lambda item: (-item[1], item[0]))
    if not ordered:
        return []
    grouped = ordered[:5]
    if len(ordered) > 5:
        grouped.append(("Other", sum(size for _, size in ordered[5:])))
    total = sum(size for _, size in grouped)
    tenths = [size * 1000 // total for _, size in grouped]
    by_remainder = sorted(range(len(grouped)),
                          key=lambda i: -(grouped[i][1] * 1000 % total))
    for i in by_remainder[:1000 - sum(tenths)]:
        tenths[i] += 1
    return [(name, units / 10) for (name, _), units in zip(grouped, tenths)]


def draw_languages(totals, project_count):
    shares = language_shares(totals)
    full_total = sum(totals.values())
    description = "; ".join(f"{name}: {size / full_total:.2%}" for name, size in
                            sorted(totals.items(), key=lambda item: -item[1])) if full_total else "No language data yet."
    art = Drawing(280, "Languages in my projects", description)
    art.text("Languages in my projects", 36, 43, 30)
    art.text(f"{project_count} public projects / by code size", 36, 72, 21, MUTED)
    palette = LANG_PALETTE_LIGHT
    if not shares:
        art.text("No language data yet", 36, 143, 27, MUTED)
    for i, (name, percent) in enumerate(shares):
        x, y = 36 + (i % 2) * 360, 111 + (i // 2) * 50
        art.text(name, x, y, 27)
        art.text(f"{percent:.1f}%", x + 246, y, 27, MUTED)
        art.parts.append(f'<rect x="{x}" y="{y+10}" width="292" height="5" rx="2.5" fill="#e5e7dd"/>')
        if percent:
            art.parts.append(f'<rect x="{x}" y="{y+10}" width="{292*percent/100:.2f}" height="5" rx="2.5" fill="{palette[i]}"/>')
    art.text("Original repositories only / excludes forks and this profile", 36, 258, 20, MUTED)
    art.save(ROOT / "assets/languages.svg")
    print("Languages: " + ", ".join(f"{name} {percent:.1f}%" for name, percent in shares))


def draw_stats(stars, views, current, days, today):
    days = sorted((d for d in days if date.fromisoformat(d["date"]) <= today), key=lambda d: d["date"])
    total = sum(d["contributionCount"] for d in days)
    view_label = f"{views:,}" if views is not None else "unavailable"
    description = (f"{stars} total stars across owned public repositories; {view_label} profile page hits; "
                   f"{current} day current streak; {total} contributions in the displayed year. "
                   f"Updated {today.isoformat()} UTC. Views are not unique visitors.")
    art = Drawing(350, "GitHub activity", description)
    for x, value, label in [(134, f"{stars:,}", "total stars"),
                             (380, view_label, "profile views"),
                             (626, f"{current} " + ("day" if current == 1 else "days"), "current streak")]:
        art.text(value, x, 61, 42 if views is not None or x != 380 else 29, center=True)
        art.text(label, x, 91, 24, MUTED, center=True)
    art.line("M 257,30 Q 255,61 257,91", DIVIDER_LIGHT)
    art.line("M 503,30 Q 501,59 503,91", DIVIDER_LIGHT)
    art.line("M 35,115 Q 370,113 725,116", DIVIDER_LIGHT)
    art.text("contributions / past year", 36, 149, 26)
    art.text(f"{total:,} contributions", 569, 149, 22, MUTED)
    start = date.fromisoformat(days[0]["date"])
    sunday = start - timedelta(days=(start.weekday() + 1) % 7)
    levels = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
              "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
    rng = random.Random(41)
    last_month = None
    for day in days:
        when = date.fromisoformat(day["date"])
        column = (when - sunday).days // 7
        row = (when.weekday() + 1) % 7
        x, y = 36 + column * 13, 193 + row * 13
        if when.month != last_month and (when.day == 1 or last_month is None):
            if when.day == 1 or when.day < 22:
                art.text(calendar.month_abbr[when.month], x, 181, 17, MUTED)
            last_month = when.month
        angle = rng.uniform(-4, 4)
        color = COLORS[levels[day["contributionLevel"]]]
        art.parts.append(f'<rect x="{x}" y="{y}" width="9.5" height="9.5" rx="2" '
                         f'transform="rotate({angle:.2f} {x+5} {y+5})" fill="{color}" '
                         f'stroke="{INK}" stroke-opacity="0.12" stroke-width="0.6">'
                         f'<title>{day["date"]}: {day["contributionCount"]} contributions</title></rect>')
    art.text(f"updated {today.strftime('%d %b %Y')} / daily", 36, 315, 19, MUTED)
    art.text("less", 556, 314, 19, MUTED)
    for i, color in enumerate(COLORS):
        art.parts.append(f'<rect x="{592+i*14}" y="303" width="10" height="10" rx="2" fill="{color}"/>')
    art.text("more", 668, 314, 19, MUTED)
    art.text("views = page hits, not unique visitors", 36, 335, 16, MUTED)
    art.save(ROOT / "assets/stats.svg")


def main():
    username = os.environ.get("PROFILE_USERNAME", "GoulagmanYt")
    if not re.fullmatch(r"[A-Za-z0-9-]+", username):
        raise ValueError("Invalid GitHub username")
    now = datetime.now(timezone.utc)
    today = now.date()
    profile = gh(f"users/{username}")
    repos = gh("--paginate", "--slurp", f"users/{username}/repos?per_page=100&type=owner")
    stars = sum(repo["stargazers_count"] for page in repos for repo in page)
    languages, project_count = language_totals([repo for page in repos for repo in page], username)
    start = today - timedelta(days=364)
    days = contributions(username, f"{start}T00:00:00Z", now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    history = list(days)
    while streak(history, today) >= (today - start).days and start > date.fromisoformat(profile["created_at"][:10]):
        end = start - timedelta(days=1)
        start -= timedelta(days=365)
        history.extend(contributions(username, f"{start}T00:00:00Z", f"{end}T23:59:59Z"))
    try:
        views = profile_views(username)
    except Exception as exc:
        print(f"Warning: profile views unavailable: {exc}")
        views = None
    draw_name("Goulagman")
    draw_content()
    draw_languages(languages, project_count)
    draw_stats(stars, views, streak(history, today), days, today)
    print(f"Generated profile for {username}: {stars} stars, {views} views, {streak(history, today)} day streak")


if __name__ == "__main__":
    main()

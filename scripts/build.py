"""Regenerate the profile SVGs from live GitHub data.

Reads GH_TOKEN from the environment and writes, for each theme (dark/light):
  assets/banner-<theme>.svg    dot-matrix name with a lightning strike
  assets/profile-<theme>.svg   TUI window: portrait print-out + system info
  assets/activity-<theme>.svg  personal + work contribution heatmap
Stdlib only, so the Action needs no installs. Animation is CSS + SMIL, both of
which GitHub keeps when it serves an SVG through <img>.
"""
import json
import os
import random
import sys
import urllib.request
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
PERSONAL, WORK = "devanshc777", "devqilin"
PORTRAIT = os.environ.get("PORTRAIT", "avatar")
W = 900

# Dark = white lightning on black, light = black lightning on white
THEMES = {
    "dark": dict(bg="#050608", panel="#0a0d12", line="#1f2a36", ink="#e6f4ff", dim="#6b7a8c",
                 key="#8fdcff", bolt="#f2fbff", glow="#7fd8ff",
                 tones=["#2a313b", "#3a4350", "#4d5866", "#626e7d", "#7a8796", "#96a3b1", "#b3bfcb"],
                 levels=["#11161d", "#1d3a52", "#2f6d96", "#55a9d8", "#c9f0ff"]),
    "light": dict(bg="#f7f8fa", panel="#ffffff", line="#d5dbe3", ink="#06080b", dim="#6a7380",
                  key="#0b3d91", bolt="#000000", glow="#3a6df0",
                  tones=["#c9ced6", "#b0b7c1", "#959eab", "#7b8592", "#606a77", "#454e5a", "#2b323c"],
                  levels=["#e9edf2", "#b9cdea", "#7aa0db", "#3561c4", "#0a1f5c"]),
}
MONO = "ui-monospace,SFMono-Regular,'JetBrains Mono',Consolas,'Liberation Mono',Menlo,monospace"

# 5x7 dot font, only the glyphs the banner needs
FONT = {
    "D": ["1110", "1001", "1001", "1001", "1001", "1001", "1110"],
    "E": ["1111", "1000", "1000", "1110", "1000", "1000", "1111"],
    "V": ["10001", "10001", "10001", "10001", "01010", "01010", "00100"],
    "A": ["0110", "1001", "1001", "1111", "1001", "1001", "1001"],
    "N": ["10001", "11001", "10101", "10101", "10011", "10001", "10001"],
    "S": ["0111", "1000", "1000", "0110", "0001", "0001", "1110"],
    "H": ["1001", "1001", "1001", "1111", "1001", "1001", "1001"],
}


# ---------------------------------------------------------------- data

def gql(query):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {os.environ['GH_TOKEN']}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    if "errors" in body:
        raise RuntimeError(body["errors"])
    return body["data"]


def calendar(login):
    d = gql(f"""{{ user(login: "{login}") {{ contributionsCollection {{
        contributionCalendar {{ totalContributions
          weeks {{ contributionDays {{ date contributionCount }} }} }} }} }} }}""")
    cal = d["user"]["contributionsCollection"]["contributionCalendar"]
    days = {x["date"]: x["contributionCount"]
            for w in cal["weeks"] for x in w["contributionDays"]}
    return cal["totalContributions"], days


def profile():
    d = gql(f"""{{ user(login: "{PERSONAL}") {{
        createdAt
        repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {{
          totalCount
          nodes {{ stargazerCount languages(first: 10) {{ edges {{ size node {{ name }} }} }} }} }}
        repositoriesContributedTo(contributionTypes: [COMMIT, PULL_REQUEST], first: 1) {{ totalCount }}
        pullRequests(states: MERGED) {{ totalCount }} }} }}""")["user"]
    langs = {}
    for repo in d["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    markup = {"HTML", "CSS", "Jupyter Notebook", "Shell", "PowerShell", "Batchfile", "Dockerfile"}
    top = [n for n, _ in sorted(langs.items(), key=lambda kv: -kv[1]) if n not in markup][:4]
    return dict(
        created=datetime.fromisoformat(d["createdAt"].replace("Z", "+00:00")),
        repos=d["repositories"]["totalCount"],
        contributed=d["repositoriesContributedTo"]["totalCount"],
        merged=d["pullRequests"]["totalCount"],
        langs=top,
    )


def recent_repos(count=6):
    """Most recently pushed public repos on the personal account, minus this profile repo."""
    d = gql(f"""{{ user(login: "{PERSONAL}") {{
        repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: {count + 1},
                     orderBy: {{field: PUSHED_AT, direction: DESC}}) {{
          nodes {{ name description url primaryLanguage {{ name }} }} }} }} }}""")
    nodes = [r for r in d["user"]["repositories"]["nodes"] if r["name"] != PERSONAL]
    return nodes[:count]


def projects_table(repos):
    def cell(r):
        blurb = r["description"] or (r["primaryLanguage"] or {}).get("name") or ""
        return f'**[{r["name"]}]({r["url"]})**<br>{blurb.replace("|", "/")}'
    lines = ["| | |", "|---|---|"]
    for i in range(0, len(repos), 2):
        pair = [cell(r) for r in repos[i:i + 2]] + [""]
        lines.append(f"| {pair[0]} | {pair[1]} |")
    return "\n".join(lines)


def update_readme(table):
    """Swap the table between the projects markers; the rest of the README is hand-written."""
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    start, end = "<!-- projects:start -->", "<!-- projects:end -->"
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    path.write_text(f"{head}{start}\n{table}\n{end}{tail}", encoding="utf-8")


def uptime(since):
    now = datetime.now(timezone.utc)
    months = (now.year - since.year) * 12 + now.month - since.month
    return f"{months // 12}y {months % 12}m"


# ---------------------------------------------------------------- shared svg bits

def svg_open(height, t, extra_css=""):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" '
        f'viewBox="0 0 {W} {height}" font-family="{MONO}">',
        "<defs>",
        '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="2.2" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '<filter id="bloom" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="6"/></filter>',
        '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">'
        f'<rect width="4" height="1" fill="{t["ink"]}" opacity="0.035"/></pattern>',
        "</defs>",
        "<style>"
        "@keyframes in{from{opacity:0}to{opacity:1}}"
        "@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}"
        # lightning: dark most of the cycle, a double flash near the end
        "@keyframes strike{0%,86%{opacity:0}87%{opacity:1}88%{opacity:.15}90%{opacity:1}95%,100%{opacity:0}}"
        "@keyframes flash{0%,86%{opacity:0}87%{opacity:.16}89%{opacity:0}90%{opacity:.1}93%,100%{opacity:0}}"
        "@keyframes flick{0%,100%{opacity:1}42%{opacity:1}43%{opacity:.35}45%{opacity:1}71%{opacity:.6}72%{opacity:1}}"
        f".fade{{opacity:0;animation:in .35s ease-out forwards}}{extra_css}"
        "text{white-space:pre}"
        "</style>",
        f'<rect width="{W}" height="{height}" rx="10" fill="{t["bg"]}"/>',
    ]


def svg_close(height, t):
    return [f'<rect width="{W}" height="{height}" rx="10" fill="url(#scan)" pointer-events="none"/>',
            f'<rect x="0.5" y="0.5" width="{W - 1}" height="{height - 1}" rx="10" fill="none" '
            f'stroke="{t["line"]}"/>', "</svg>"]


def bolt(rng, x0, y0, x1, y1, depth=5, spread=0.32):
    """Midpoint-displacement lightning: returns a jagged list of points."""
    pts = [(x0, y0), (x1, y1)]
    for _ in range(depth):
        out = [pts[0]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, by - ay
            off = rng.uniform(-spread, spread)
            out.append(((ax + bx) / 2 - dy * off, (ay + by) / 2 + dx * off))
            out.append((bx, by))
        pts = out
        spread *= 0.62
    return pts


def poly(pts):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def bolt_group(t, rng, x0, y0, x1, y1, period, delay, width=1.6):
    """A main bolt with two branches, flashing on the strike keyframes."""
    main = bolt(rng, x0, y0, x1, y1)
    parts = [main]
    for _ in range(2):
        i = rng.randrange(len(main) // 4, len(main) * 3 // 4)
        bx, by = main[i]
        parts.append(bolt(rng, bx, by, bx + rng.uniform(-90, 90), by + rng.uniform(30, 70), depth=4))
    style = f"animation:strike {period}s linear {delay}s infinite;opacity:0"
    g = [f'<g style="{style}">']
    for k, p in enumerate(parts):
        w = width if k == 0 else width * 0.55
        g.append(f'<polyline points="{poly(p)}" fill="none" stroke="{t["glow"]}" stroke-width="{w * 4}" '
                 f'opacity=".45" filter="url(#bloom)"/>')
        g.append(f'<polyline points="{poly(p)}" fill="none" stroke="{t["bolt"]}" stroke-width="{w}" '
                 'stroke-linejoin="round"/>')
    g.append("</g>")
    return g


# ---------------------------------------------------------------- banner

def banner(t):
    h, cell, gap = 168, 11, 3
    word = "DEVANSH"
    widths = [len(FONT[c][0]) for c in word]
    cols = sum(widths) + 2 * (len(word) - 1)
    x0 = (W - cols * (cell + gap)) // 2
    y0 = 34
    out = svg_open(h, t, extra_css=".px{animation:in .25s ease-out forwards,flick 6s steps(1) infinite}")
    out.append(f'<text x="24" y="22" font-size="10" fill="{t["dim"]}">'
               f'devansh@chowdhary:~$ ./boot --profile</text>')
    # faint grid of unlit pixels behind the word, like an LED board
    out.append(f'<g fill="{t["ink"]}" opacity=".05">')
    for r in range(7):
        for c in range(cols):
            out.append(f'<rect x="{x0 + c * (cell + gap)}" y="{y0 + r * (cell + gap)}" '
                       f'width="{cell}" height="{cell}" rx="2"/>')
    out.append("</g>")
    out.append(f'<g fill="{t["ink"]}" filter="url(#glow)">')
    col = 0
    for li, (ch, wd) in enumerate(zip(word, widths)):
        delay = 0.15 + li * 0.12
        for r, bits in enumerate(FONT[ch]):
            for c, b in enumerate(bits):
                if b == "1":
                    out.append(f'<rect class="px" x="{x0 + (col + c) * (cell + gap)}" '
                               f'y="{y0 + r * (cell + gap)}" width="{cell}" height="{cell}" rx="2" '
                               f'style="opacity:0;animation-delay:{delay:.2f}s,{delay + 1:.2f}s"/>')
        col += wd + 2
    out.append("</g>")
    sub = "AI & backend engineer  //  ships production systems"
    sy = y0 + 7 * (cell + gap) + 30
    out.append(f'<clipPath id="type"><rect x="0" y="{sy - 14}" width="0" height="20">'
               f'<animate attributeName="width" begin="1.1s" dur="1.6s" fill="freeze" calcMode="discrete" '
               f'values="{";".join(str(int(W / 2 - len(sub) * 3.9 + i * 7.8)) for i in range(len(sub) + 1))}"/>'
               "</rect></clipPath>")
    out.append(f'<text x="{W / 2}" y="{sy}" text-anchor="middle" font-size="13" fill="{t["key"]}" '
               f'clip-path="url(#type)">{escape(sub)}</text>')
    rng = random.Random(7)
    out += bolt_group(t, rng, 120, -4, 230, h - 20, period=7, delay=2.2)
    out += bolt_group(t, rng, W - 90, -4, W - 220, h - 40, period=9, delay=5.1, width=1.2)
    out.append(f'<rect width="{W}" height="{h}" rx="10" fill="{t["bolt"]}" '
               'style="opacity:0;animation:flash 7s linear 2.2s infinite"/>')
    return "\n".join(out + svg_close(h, t))


# ---------------------------------------------------------------- profile window

def window_chrome(t, h, title):
    return [
        f'<rect x="12" y="12" width="{W - 24}" height="{h - 24}" rx="8" fill="{t["panel"]}" '
        f'stroke="{t["line"]}"/>',
        f'<line x1="12" y1="40" x2="{W - 12}" y2="40" stroke="{t["line"]}"/>',
        *[f'<circle cx="{30 + i * 16}" cy="26" r="4.5" fill="none" stroke="{t["dim"]}"/>' for i in range(3)],
        f'<text x="{W / 2}" y="30" text-anchor="middle" font-size="11" fill="{t["dim"]}">{escape(title)}</text>',
        f'<text x="{W - 30}" y="30" text-anchor="end" font-size="10" fill="{t["key"]}">'
        f'<tspan style="animation:blink 1.2s steps(1) infinite">●</tspan> LIVE</text>',
    ]


def pane(t, x, y, w, h, label):
    return [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="none" stroke="{t["line"]}"/>',
            f'<rect x="{x + 12}" y="{y - 7}" width="{len(label) * 7 + 12}" height="14" fill="{t["panel"]}"/>',
            f'<text x="{x + 18}" y="{y + 4}" font-size="10" letter-spacing="1.5" fill="{t["key"]}">'
            f'{label}</text>']


def portrait_dots(t, grid, x0, y0, size):
    n = len(grid["tone"])
    flip = grid.get("flip_on_light") and t is THEMES["light"]
    step = size / n
    # centre on the lit cells, not the source crop
    lit = [x for row in grid["tone"] for x, v in enumerate(row) if v != "0"]
    x0 += (n - 1 - max(lit) - min(lit)) / 2 * step
    tones, edges = [[] for _ in t["tones"]], []
    for y in range(n):
        for x in range(n):
            v = int(grid["tone"][y][x])
            if flip and v:
                v = 10 - v
            r = step / 2 * min(1.0, (v / 9) ** 0.9)
            if r < 0.45:
                continue
            cx, cy = x0 + x * step + step / 2, y0 + y * step + step / 2
            dot = f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.2f}"/>'
            if grid["edge"][y][x] == "1":
                edges.append(dot)
            else:
                tones[min(len(tones) - 1, v * len(tones) // 10)].append(dot)
    out = []
    for color, dots in zip(t["tones"], tones):
        if dots:
            out.append(f'<g fill="{color}">{"".join(dots)}</g>')
    # edges are the lightning: bright, glowing, flickering on their own clock
    out.append(f'<g fill="{t["bolt"]}" filter="url(#glow)" '
               f'style="animation:flick 4.3s steps(1) 4s infinite">{"".join(edges)}</g>')
    return out


def profile_svg(t, grid, rows):
    h = 470
    out = svg_open(h, t)
    out += window_chrome(t, h, "devansh@chowdhary: ~/profile-scan --live")

    # left pane: portrait printing top-to-bottom
    px, py, pw, ph = 30, 62, 388, 386
    out += pane(t, px, py, pw, ph, "VISUAL.MAP")
    size = 328
    ix, iy = px + (pw - size) / 2, py + 20
    print_dur = 3.6
    out.append(f'<clipPath id="print"><rect x="{ix}" y="{iy}" width="{size}" height="0">'
               f'<animate attributeName="height" from="0" to="{size}" begin="0.4s" dur="{print_dur}s" '
               'fill="freeze"/></rect></clipPath>')
    out.append('<g clip-path="url(#print)">')
    out += portrait_dots(t, grid, ix, iy, size)
    out.append("</g>")
    # print head: a bright bar riding the bottom of the reveal, gone once done
    out.append(f'<rect x="{ix - 6}" y="{iy}" width="{size + 12}" height="2" fill="{t["bolt"]}" '
               f'filter="url(#glow)" opacity="0">'
               f'<set attributeName="opacity" to="1" begin="0.4s"/>'
               f'<animate attributeName="y" from="{iy}" to="{iy + size}" begin="0.4s" dur="{print_dur}s" '
               'fill="freeze"/>'
               f'<set attributeName="opacity" to="0" begin="{0.4 + print_dur}s"/></rect>')
    # progress readout, swapped in steps
    ty = py + ph - 10
    steps = 10
    for i in range(steps + 1):
        pct = i * 100 // steps
        start = 0.4 + print_dur * i / steps
        label = f"PRINTING {pct:3d}%" if i < steps else "SCAN COMPLETE ✓"
        end = f' end="{0.4 + print_dur * (i + 1) / steps:.2f}s"' if i < steps else ""
        out.append(f'<text x="{px + pw - 14}" y="{ty}" text-anchor="end" font-size="10" '
                   f'fill="{t["key"]}" opacity="0"><set attributeName="opacity" to="1" '
                   f'begin="{start:.2f}s"{end}/>{label}</text>')
    out.append(f'<text x="{px + 14}" y="{ty}" font-size="10" fill="{t["dim"]}">portrait.svg  {len(grid["tone"])}×{len(grid["tone"])}</text>')

    # right pane: system info lines appear one by one
    sx, sy, sw = 434, 62, W - 30 - 434
    out += pane(t, sx, sy, sw, ph, "SYSTEM.INFO")
    lh = 21.5
    for i, row in enumerate(rows):
        y = sy + 32 + i * lh
        delay = 0.5 + i * 0.16
        if row[0] == "rule":
            out.append(f'<line class="fade" x1="{sx + 14}" y1="{y - 4}" x2="{sx + sw - 14}" y2="{y - 4}" '
                       f'stroke="{t["line"]}" stroke-dasharray="2 3" style="animation-delay:{delay:.2f}s"/>')
            continue
        key, val = row
        out.append(f'<text class="fade" x="{sx + 16}" y="{y}" font-size="11.5" '
                   f'style="animation-delay:{delay:.2f}s">'
                   f'<tspan fill="{t["dim"]}">{escape(key)}</tspan>'
                   f'<tspan x="{sx + 128}" fill="{t["ink"]}">{escape(val)}</tspan></text>')
    end_y = sy + 32 + len(rows) * lh
    out.append(f'<text class="fade" x="{sx + 16}" y="{end_y}" font-size="11.5" fill="{t["key"]}" '
               f'style="animation-delay:{0.5 + len(rows) * 0.16:.2f}s">&gt; '
               f'<tspan style="animation:blink 1s steps(1) infinite">█</tspan></text>')

    rng = random.Random(11)
    out += bolt_group(t, rng, px + 40, 44, px + 150, py + 160, period=11, delay=6.5, width=1.1)
    return "\n".join(out + svg_close(h, t))


# ---------------------------------------------------------------- activity

def activity(t, merged, p_total, w_total):
    days = sorted(merged)
    first = date.fromisoformat(days[0])
    cell, gap, top = 12, 3, 62
    weeks = (date.fromisoformat(days[-1]) - first).days // 7 + 1
    h = top + 7 * (cell + gap) + 44
    nonzero = sorted(v for v in merged.values() if v)
    q = [nonzero[int(len(nonzero) * f)] for f in (0.25, 0.5, 0.75)] if nonzero else [1, 1, 1]

    def level(v):
        return 0 if v == 0 else 1 + sum(v > x for x in q)

    grid_w = weeks * (cell + gap)
    left = (W - grid_w) // 2
    out = svg_open(h, t, extra_css="@keyframes sweep{from{transform:translateX(0)}to{transform:"
                                   f"translateX({grid_w}px)}}}}")
    total = p_total + w_total
    out.append(f'<text x="{left}" y="30" font-size="10" fill="{t["dim"]}">'
               f'&gt; github activity heatmap // contribution stream merged</text>')
    out.append(f'<text x="{left}" y="48" font-size="14" fill="{t["ink"]}">'
               f'<tspan font-weight="bold" fill="{t["key"]}">{total:,}</tspan> contributions in the last year'
               f'<tspan font-size="11" fill="{t["dim"]}">   {p_total:,} @{PERSONAL} + {w_total:,} @{WORK}</tspan>'
               "</text>")
    last_month = None
    hot = []
    for d in days:
        dt = date.fromisoformat(d)
        col = (dt - first).days // 7
        row = (dt.weekday() + 1) % 7      # GitHub weeks start on Sunday
        x, y = left + col * (cell + gap), top + row * (cell + gap)
        if row == 0 and dt.month != last_month and dt.day <= 7:
            out.append(f'<text x="{x}" y="{top + 7 * (cell + gap) + 12}" fill="{t["dim"]}" '
                       f'font-size="9">{dt:%b}</text>')
            last_month = dt.month
        lv = level(merged[d])
        rect = (f'<rect class="fade" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
                f'fill="{t["levels"][lv]}" style="animation-delay:{col * 0.02:.2f}s">'
                f'<title>{d}: {merged[d]}</title></rect>')
        (hot if lv >= 3 else out).append(rect)
    out.append(f'<g filter="url(#glow)">{"".join(hot)}</g>')
    # scan beam sweeping the grid
    out.append(f'<rect x="{left - 4}" y="{top - 6}" width="3" height="{7 * (cell + gap) + 9}" '
               f'fill="{t["bolt"]}" opacity=".55" filter="url(#glow)" '
               'style="animation:sweep 6s linear 1.4s infinite"/>')
    ly = h - 16
    lx = left + grid_w - 5 * (cell + gap) - 64
    out.append(f'<text x="{lx}" y="{ly + 9}" fill="{t["dim"]}" font-size="9">less</text>')
    for i, c in enumerate(t["levels"]):
        out.append(f'<rect x="{lx + 28 + i * (cell + gap)}" y="{ly}" width="{cell - 2}" height="{cell - 2}" '
                   f'rx="2" fill="{c}"/>')
    out.append(f'<text x="{lx + 30 + 5 * (cell + gap)}" y="{ly + 9}" fill="{t["dim"]}" font-size="9">more</text>')
    return "\n".join(out + svg_close(h, t))


# ---------------------------------------------------------------- main

def main():
    p_total, p_days = calendar(PERSONAL)
    w_total, w_days = calendar(WORK)
    merged = {d: p_days.get(d, 0) + w_days.get(d, 0) for d in set(p_days) | set(w_days)}
    active = sum(1 for v in merged.values() if v)
    me = profile()
    grid = json.loads((ASSETS / "portraits" / f"{PORTRAIT}.json").read_text(encoding="utf-8"))

    rows = [
        ("Subject", "Devansh Chowdhary"),
        ("Handle", f"@{PERSONAL} · @{WORK}"),
        ("Role", "AI & Python Developer, Qilin Lab"),
        ("Study", "B.Tech CSE, Manipal Univ. Jaipur"),
        ("Status", "Building | Shipping | Open source"),
        ("rule",),
        ("Languages", ", ".join(me["langs"])),
        ("Repositories", f"{me['repos']} public · {me['contributed']} contributed"),
        ("Contributions", f"{p_total + w_total:,} / year · {active} active days"),
        ("Merged PRs", str(me["merged"])),
        ("Uptime", uptime(me["created"])),
        ("rule",),
        ("SIH 2025", "MindEase · All India Rank 6"),
        ("Patent", "CAENS · filed + published"),
        ("Open source", "Apicurio Registry (CNCF)"),
        ("180DC MUJ", "Technical Secretary"),
    ]
    for name, t in THEMES.items():
        (ASSETS / f"banner-{name}.svg").write_text(banner(t), encoding="utf-8")
        (ASSETS / f"profile-{name}.svg").write_text(profile_svg(t, grid, rows), encoding="utf-8")
        (ASSETS / f"activity-{name}.svg").write_text(activity(t, merged, p_total, w_total), encoding="utf-8")
    repos = recent_repos()
    update_readme(projects_table(repos))
    print(f"projects: {[r['name'] for r in repos]}", file=sys.stderr)
    print(f"ok: {p_total} personal + {w_total} work, {active} active days, "
          f"portrait={PORTRAIT}, langs={me['langs']}", file=sys.stderr)


if __name__ == "__main__":
    main()

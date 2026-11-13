#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Render a star constellation as ASCII art.

Usage:
    python3 constellation_ascii.py <constellation name> [options]

Examples:
    python3 constellation_ascii.py orion
    python3 constellation_ascii.py "Ursa Major" --maglimit 4 --width 80

Star coordinates are fetched online from the HYG star database
(https://github.com/astronexus/HYG-Database) and cached locally so that
subsequent runs are fast and offline-capable.
"""

import argparse
import csv
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone

# IAU 3-letter abbreviation -> full constellation name.
# Used to translate a human-typed name into the `con` column of the catalog.
CONSTELLATIONS = {
    "and": "Andromeda", "ant": "Antlia", "aps": "Apus", "aqr": "Aquarius",
    "aql": "Aquila", "ara": "Ara", "ari": "Aries", "aur": "Auriga",
    "boo": "Bootes", "cae": "Caelum", "cam": "Camelopardalis", "cnc": "Cancer",
    "cvn": "Canes Venatici", "cma": "Canis Major", "cmi": "Canis Minor",
    "cap": "Capricornus", "car": "Carina", "cas": "Cassiopeia",
    "cen": "Centaurus", "cep": "Cepheus", "cet": "Cetus", "cha": "Chamaeleon",
    "cir": "Circinus", "col": "Columba", "com": "Coma Berenices",
    "cra": "Corona Australis", "crb": "Corona Borealis", "crv": "Corvus",
    "crt": "Crater", "cru": "Crux", "cyg": "Cygnus", "del": "Delphinus",
    "dor": "Dorado", "dra": "Draco", "equ": "Equuleus", "eri": "Eridanus",
    "for": "Fornax", "gem": "Gemini", "gru": "Grus", "her": "Hercules",
    "hor": "Horologium", "hya": "Hydra", "hyi": "Hydrus", "ind": "Indus",
    "lac": "Lacerta", "leo": "Leo", "lmi": "Leo Minor", "lep": "Lepus",
    "lib": "Libra", "lup": "Lupus", "lyn": "Lynx", "lyr": "Lyra",
    "men": "Mensa", "mic": "Microscopium", "mon": "Monoceros", "mus": "Musca",
    "nor": "Norma", "oct": "Octans", "oph": "Ophiuchus", "ori": "Orion",
    "pav": "Pavo", "peg": "Pegasus", "per": "Perseus", "phe": "Phoenix",
    "pic": "Pictor", "psc": "Pisces", "psa": "Piscis Austrinus",
    "pup": "Puppis", "pyx": "Pyxis", "ret": "Reticulum", "sge": "Sagitta",
    "sgr": "Sagittarius", "sco": "Scorpius", "scl": "Sculptor",
    "sct": "Scutum", "ser": "Serpens", "sex": "Sextans", "tau": "Taurus",
    "tel": "Telescopium", "tri": "Triangulum", "tra": "Triangulum Australe",
    "tuc": "Tucana", "uma": "Ursa Major", "umi": "Ursa Minor", "vel": "Vela",
    "vir": "Virgo", "vol": "Volans", "vul": "Vulpecula",
}

# Candidate URLs for the HYG catalog (CSV). Tried in order.
CATALOG_URLS = [
    "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv",
    "https://raw.githubusercontent.com/astronexus/HYG-Database/master/hyg/CURRENT/hygdata_v41.csv",
]

# Per-user cache (not /tmp: a predictable shared path lets other users plant
# symlinks that root would then write through when run from cron).
CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "constellation-ascii")
CACHE_PATH = os.path.join(CACHE_DIR, "hygdata_current.csv")

# Stellarium "modern" sky culture: each constellation's stick-figure as
# polylines of HIP star numbers. We use it to know which stars are part of the
# constellation (the line endpoints), not to draw the lines.
LINES_URLS = [
    "https://raw.githubusercontent.com/Stellarium/stellarium-skycultures/master/western/index.json",
]

LINES_CACHE = os.path.join(CACHE_DIR, "stellarium_western_index.json")


def _download(url, path, min_size):
    """Fetch url into path atomically; raise if the result is too small."""
    req = urllib.request.Request(url, headers={"User-Agent": "constellation-ascii/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if len(data) < min_size:
        raise ValueError("downloaded file looks too small")
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return len(data)


def resolve_abbrev(name):
    """Turn a user-supplied name into a 3-letter constellation abbreviation."""
    key = name.strip().lower()
    if key in CONSTELLATIONS:  # user already gave an abbreviation
        return key
    for abbr, full in CONSTELLATIONS.items():
        if full.lower() == key:
            return abbr
    # forgiving match: ignore punctuation/spacing
    norm = key.replace("-", " ").replace(".", "").strip()
    for abbr, full in CONSTELLATIONS.items():
        if full.lower() == norm:
            return abbr
    # spaceless match, so hostnames like "ursamajor" / "canismajor" resolve
    collapsed = "".join(key.split())
    for abbr, full in CONSTELLATIONS.items():
        if "".join(full.lower().split()) == collapsed:
            return abbr
    return None


def ensure_catalog():
    """Return the path to the cached catalog, downloading it if needed."""
    if os.path.exists(CACHE_PATH) and os.path.getsize(CACHE_PATH) > 1_000_000:
        return CACHE_PATH

    last_err = None
    for url in CATALOG_URLS:
        try:
            sys.stderr.write(f"Fetching star catalog from {url} ...\n")
            size = _download(url, CACHE_PATH, 1_000_000)
            sys.stderr.write(f"Cached catalog at {CACHE_PATH} ({size // 1024} KiB)\n")
            return CACHE_PATH
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            last_err = exc
            sys.stderr.write(f"  failed: {exc}\n")
    raise SystemExit(f"Could not download star catalog. Last error: {last_err}")


def asterism_lines(abbr):
    """Return the constellation's stick-figure as a list of HIP polylines.

    Each polyline is a list of HIP numbers; consecutive pairs are line
    segments. The flattened set of these HIPs is the stars "part of" the
    constellation. Returns [] if the line data can't be fetched (the script
    still works, just without lines or the keep-the-figure guarantee).
    """
    if not (os.path.exists(LINES_CACHE) and os.path.getsize(LINES_CACHE) > 1000):
        for url in LINES_URLS:
            try:
                sys.stderr.write(f"Fetching constellation lines from {url} ...\n")
                _download(url, LINES_CACHE, 1000)
                break
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"  failed: {exc}\n")
        else:
            sys.stderr.write("  warning: continuing without line data.\n")
            return []

    try:
        with open(LINES_CACHE, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 - corrupt cache, ignore
        return []

    for con in data.get("constellations", []):
        if (con.get("iau") or "").strip().lower() == abbr:
            polylines = []
            for line in con.get("lines", []):
                # A polyline is a run of HIP numbers, optionally led by a style
                # token like "thin"; keep only the integer HIP values.
                polylines.append([h for h in line if isinstance(h, int)])
            return polylines
    return []


def load_stars(abbr, mag_limit, top=None, keep_hips=frozenset()):
    """Read the stars of a constellation to plot.

    Selection = (every star whose HIP is in `keep_hips`, i.e. part of the
    figure) UNION (stars brighter than `mag_limit`, optionally trimmed to the
    `top` brightest). Figure stars are always kept regardless of magnitude --
    and regardless of which constellation officially owns them, since some
    stick figures borrow a star from a neighbour (e.g. Auriga draws to Elnath,
    which sits in Taurus; the Great Square of Pegasus to Alpheratz in
    Andromeda).
    """
    path = ensure_catalog()
    figure, extra = [], []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                hip = int(row["hip"])
            except (KeyError, ValueError):
                hip = None
            in_con = (row.get("con") or "").strip().lower() == abbr
            is_figure = hip in keep_hips
            if not (in_con or is_figure):
                continue
            try:
                mag = float(row["mag"])
                ra = float(row["ra"])     # hours (0-24)
                dec = float(row["dec"])   # degrees (-90..90)
            except (KeyError, ValueError):
                continue
            star = {
                "ra": ra,
                "dec": dec,
                "mag": mag,
                "hip": hip,
                "name": (row.get("proper") or "").strip(),
                "figure": is_figure,
            }
            if is_figure:
                figure.append(star)
            elif mag <= mag_limit:
                extra.append(star)
    if top is not None:
        extra.sort(key=lambda s: s["mag"])
        extra = extra[:top]
    return figure + extra


def glyph_for_mag(mag):
    """Pick a denser glyph for brighter (lower-magnitude) stars."""
    if mag <= 1.0:
        return "@"
    if mag <= 2.0:
        return "O"
    if mag <= 3.0:
        return "*"
    if mag <= 4.0:
        return "+"
    return "."


def _mean_direction(stars):
    """Centre of the constellation as a (ra0, dec0) in radians.

    Averages unit vectors so it's correct even across the 0h/24h RA seam.
    """
    sx = sy = sz = 0.0
    for s in stars:
        ra = math.radians(s["ra"] * 15.0)
        dec = math.radians(s["dec"])
        sx += math.cos(dec) * math.cos(ra)
        sy += math.cos(dec) * math.sin(ra)
        sz += math.sin(dec)
    n = len(stars)
    sx, sy, sz = sx / n, sy / n, sz / n
    norm = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
    sx, sy, sz = sx / norm, sy / norm, sz / norm
    return math.atan2(sy, sx), math.asin(max(-1.0, min(1.0, sz)))


CELL_ASPECT = 2.0  # fallback: terminal cells are ~twice as tall as wide
RESET = "\033[0m"
LINE_GREY = 96     # truecolor value for connecting lines (dim, recedes)

# Per-planet marker glyph (single ASCII char, none colliding with the star
# glyphs @ O * + . or line glyphs - | / \\) and a distinctive truecolor hue.
PLANET_GLYPH = {
    "Mercury": "M", "Venus": "V", "Mars": "m", "Jupiter": "J",
    "Saturn": "S", "Uranus": "U", "Neptune": "N",
}
# Astronomical symbols (opt-in: these are ambiguous-width and may misalign in
# some terminals/fonts, so the ASCII letters above stay the default).
PLANET_SYMBOL = {
    "Mercury": "☿", "Venus": "♀", "Mars": "♂", "Jupiter": "♃",
    "Saturn": "♄", "Uranus": "♅", "Neptune": "♆",
}
PLANET_COLOR = {
    "Mercury": (178, 153, 110), "Venus": (235, 220, 150),
    "Mars": (210, 70, 45), "Jupiter": (215, 160, 110),
    "Saturn": (220, 200, 140), "Uranus": (130, 205, 215),
    "Neptune": (95, 120, 235),
}


AUTO_MAG_MAX = 8.0  # catalog is complete well past this
GREY_PER_MAG = 32  # ~7 magnitudes from white to black


def _grey(value):
    """Truecolor SGR for a grey of the given 0-255 value."""
    v = max(0, min(255, int(value)))
    return f"\033[38;2;{v};{v};{v}m"


def _rgb(r, g, b):
    """Truecolor SGR for an explicit RGB triple."""
    return f"\033[38;2;{r};{g};{b}m"


# --- Planetary ephemeris (Paul Schlyter's low-precision method) --------------
# Mean Keplerian elements as functions of `d` = days since 2000 Jan 0.0 TT.
# Each returns (N, i, w, a, e, M): node, inclination, arg.peri (deg), semi-
# major axis (AU), eccentricity, mean anomaly (deg). Good to ~1-2 arcminutes
# for the naked-eye planets — far better than a character cell, and offline.
# Reference: http://www.stjarnhimlen.se/comp/ppcomp.html
_PLANET_ELEMENTS = [
    ("Mercury", lambda d: (48.3313 + 3.24587e-5 * d, 7.0047 + 5.00e-8 * d,
                           29.1241 + 1.01444e-5 * d, 0.387098,
                           0.205635 + 5.59e-10 * d, 168.6562 + 4.0923344368 * d)),
    ("Venus", lambda d: (76.6799 + 2.46590e-5 * d, 3.3946 + 2.75e-8 * d,
                         54.8910 + 1.38374e-5 * d, 0.723330,
                         0.006773 - 1.302e-9 * d, 48.0052 + 1.6021302244 * d)),
    ("Mars", lambda d: (49.5574 + 2.11081e-5 * d, 1.8497 - 1.78e-8 * d,
                        286.5016 + 2.92961e-5 * d, 1.523688,
                        0.093405 + 2.516e-9 * d, 18.6021 + 0.5240207766 * d)),
    ("Jupiter", lambda d: (100.4542 + 2.76854e-5 * d, 1.3030 - 1.557e-7 * d,
                           273.8777 + 1.64505e-5 * d, 5.20256,
                           0.048498 + 4.469e-9 * d, 19.8950 + 0.0830853001 * d)),
    ("Saturn", lambda d: (113.6634 + 2.38980e-5 * d, 2.4886 - 1.081e-7 * d,
                          339.3939 + 2.97661e-5 * d, 9.55475,
                          0.055546 - 9.499e-9 * d, 316.9670 + 0.0334442282 * d)),
    ("Uranus", lambda d: (74.0005 + 1.3978e-5 * d, 0.7733 + 1.9e-8 * d,
                          96.6612 + 3.0565e-5 * d, 19.18171 - 1.55e-8 * d,
                          0.047318 + 7.45e-9 * d, 142.5905 + 0.011725806 * d)),
    ("Neptune", lambda d: (131.7806 + 3.0173e-5 * d, 1.7700 - 2.55e-7 * d,
                           272.8461 - 6.027e-6 * d, 30.05826 + 3.313e-8 * d,
                           0.008606 + 2.15e-9 * d, 260.2471 + 0.005995147 * d)),
]


def _day_number(dt):
    """Schlyter day number `d` for a UTC datetime (days since 2000 Jan 0.0)."""
    y, m, day = dt.year, dt.month, dt.day
    d = 367 * y - (7 * (y + (m + 9) // 12)) // 4 + (275 * m) // 9 + day - 730530
    return d + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24.0


def _eccentric_anomaly(m_rad, e):
    """Solve Kepler's equation M = E - e sin E (radians) by Newton iteration."""
    e_anom = m_rad + e * math.sin(m_rad) * (1.0 + e * math.cos(m_rad))
    for _ in range(100):
        delta = (e_anom - e * math.sin(e_anom) - m_rad) / (1.0 - e * math.cos(e_anom))
        e_anom -= delta
        if abs(delta) < 1e-9:
            break
    return e_anom


def _sun_rect(d):
    """Sun's geocentric ecliptic (xs, ys) and the obliquity, all for day d."""
    w = math.radians((282.9404 + 4.70935e-5 * d) % 360)
    e = 0.016709 - 1.151e-9 * d
    m = math.radians((356.0470 + 0.9856002585 * d) % 360)
    obl = math.radians(23.4393 - 3.563e-7 * d)
    e_anom = _eccentric_anomaly(m, e)
    xv = math.cos(e_anom) - e
    yv = math.sqrt(1.0 - e * e) * math.sin(e_anom)
    v = math.atan2(yv, xv)
    r = math.hypot(xv, yv)
    lon = v + w
    return r * math.cos(lon), r * math.sin(lon), obl


def _planet_radec(elements, d, xs, ys, obl):
    """Geocentric (RA hours, Dec degrees) for one planet's elements at day d."""
    n_node, inc, w, a, e, m = elements(d)
    n_node = math.radians(n_node % 360)
    inc = math.radians(inc)
    w = math.radians(w % 360)
    m = math.radians(m % 360)
    e_anom = _eccentric_anomaly(m, e)
    xv = a * (math.cos(e_anom) - e)
    yv = a * math.sqrt(1.0 - e * e) * math.sin(e_anom)
    v = math.atan2(yv, xv)
    r = math.hypot(xv, yv)
    # Heliocentric ecliptic rectangular coordinates.
    vw = v + w
    xh = r * (math.cos(n_node) * math.cos(vw) - math.sin(n_node) * math.sin(vw) * math.cos(inc))
    yh = r * (math.sin(n_node) * math.cos(vw) + math.cos(n_node) * math.sin(vw) * math.cos(inc))
    zh = r * (math.sin(vw) * math.sin(inc))
    # Geocentric: add the Earth->Sun vector, then tilt to the equator.
    xg, yg, zg = xh + xs, yh + ys, zh
    xe = xg
    ye = yg * math.cos(obl) - zg * math.sin(obl)
    ze = yg * math.sin(obl) + zg * math.cos(obl)
    ra = math.degrees(math.atan2(ye, xe)) % 360
    dec = math.degrees(math.atan2(ze, math.hypot(xe, ye)))
    return ra / 15.0, dec


def compute_planets(when=None):
    """Geocentric positions of the naked-eye planets at `when` (UTC, now if None).

    Returns a list of {name, ra (hours), dec (degrees)} in Sun-outward order.
    """
    if when is None:
        when = datetime.now(timezone.utc)
    d = _day_number(when)
    xs, ys, obl = _sun_rect(d)
    return [{"name": name, "ra": ra, "dec": dec}
            for name, elements in _PLANET_ELEMENTS
            for ra, dec in [_planet_radec(elements, d, xs, ys, obl)]]


def _ioctl_cell_aspect():
    """Cell height:width from the TIOCGWINSZ pixel fields, or None."""
    try:
        import fcntl
        import struct
        import termios
    except ImportError:
        return None
    for stream in (sys.stdout, sys.stdin, sys.stderr):
        try:
            rows, cols, xpix, ypix = struct.unpack(
                "HHHH", fcntl.ioctl(stream.fileno(), termios.TIOCGWINSZ,
                                    struct.pack("HHHH", 0, 0, 0, 0)))
        except Exception:  # noqa: BLE001 - not a tty / unsupported
            continue
        if rows and cols and xpix and ypix:
            return (ypix / rows) / (xpix / cols)
    return None


def _query_cell_aspect():
    """Ask the terminal for its cell size in pixels via CSI 16 t, or None."""
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        return None
    try:
        import re
        import select
        import termios
        import tty
    except ImportError:
        return None
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
    except Exception:  # noqa: BLE001
        return None
    try:
        tty.setraw(fd)
        sys.stdout.write("\033[16t")
        sys.stdout.flush()
        buf = ""
        while len(buf) < 32:
            ready, _, _ = select.select([fd], [], [], 0.15)
            if not ready:
                break
            ch = os.read(fd, 1).decode("latin-1")
            buf += ch
            if ch == "t":
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    m = re.search(r"\033\[6;(\d+);(\d+)t", buf)  # CSI 6 ; height ; width t
    if m:
        h, w = int(m.group(1)), int(m.group(2))
        if w:
            return h / w
    return None


def detect_cell_aspect(default=CELL_ASPECT):
    """Best-effort character cell height:width ratio reported by the terminal."""
    return _ioctl_cell_aspect() or _query_cell_aspect() or default


def _line_glyph(dc, dr):
    """Pick an ASCII glyph for a segment running (dc, dr) in screen cells."""
    adc, adr = abs(dc), abs(dr)
    if adr * 2 < adc:
        return "-"
    if adc * 2 < adr:
        return "|"
    # row grows downward, so same-sign (right+down / left+up) leans "\".
    return "\\" if (dc > 0) == (dr > 0) else "/"


def _draw_segment(grid, c0, r0, c1, r1, glyph):
    """Bresenham line into `grid`, only filling blank cells (stars win)."""
    h = len(grid)
    w = len(grid[0])
    dc = abs(c1 - c0)
    dr = -abs(r1 - r0)
    sc = 1 if c0 < c1 else -1
    sr = 1 if r0 < r1 else -1
    err = dc + dr
    while True:
        if 0 <= r0 < h and 0 <= c0 < w and grid[r0][c0] == " ":
            grid[r0][c0] = glyph
        if c0 == c1 and r0 == r1:
            break
        e2 = 2 * err
        if e2 >= dr:
            err += dr
            c0 += sc
        if e2 <= dc:
            err += dc
            r0 += sr


def auto_mag_limit(deg_per_row):
    """Faintest magnitude to plot so stars per cell stay roughly constant.

    Star counts grow ~10**(0.6*mag) at these magnitudes (they double every
    half magnitude), cell area with deg_per_row**2, so the limit drops 2/0.6
    mag per tenfold increase in degrees per row. Calibrated to
    mag 6.5 at 0.7 deg/row (Bootes at 80 columns).
    """
    return min(AUTO_MAG_MAX, 6.5 - (2 / 0.6) * math.log10(deg_per_row / 0.7))


def render(stars, width=None, height=None, lines=None,
           cell_aspect=CELL_ASPECT, color=False, planets=None, symbols=False,
           auto_mag=False):
    """Project stars onto a character grid.

    Returns (art, planets_drawn, stars_drawn).

    Uses an azimuthal stereographic projection on the plane tangent at the
    constellation's centre. Being azimuthal, it keeps the figure's shape
    around that centre (conformal: angles preserved), and it handles any sky
    position including the poles and the RA seam without special-casing.

    `width`/`height` may be None: the missing one is derived from the figure's
    aspect ratio so the shape isn't distorted. If both are None, width is 80.
    `cell_aspect` is the character cell height:width ratio (columns are
    stretched by it so shapes aren't squished). If `lines` (a list of HIP
    polylines) is given, the connecting segments are drawn beneath the stars.
    When `color` is set, stars are shaded grey by brightness (bright = white).
    `planets` is an optional list of {name, ra, dec}; any that project inside
    the rendered field are drawn on top, and their names are returned. When
    `symbols` is set, planets use their astronomical symbol (☿♀♂…) glyphs.
    With `auto_mag`, non-figure stars fainter than auto_mag_limit() for the
    resulting scale are dropped, so wide constellations don't fill every cell.
    """
    if not stars:
        return "", [], []

    ra0, dec0 = _mean_direction(stars)
    sin_d0, cos_d0 = math.sin(dec0), math.cos(dec0)

    def project(ra_hours, dec_deg):
        # tangent-plane stereographic; px east-positive, py north-positive.
        d_ra = math.radians(ra_hours * 15.0) - ra0
        dec = math.radians(dec_deg)
        sin_d, cos_d = math.sin(dec), math.cos(dec)
        cos_c = sin_d0 * sin_d + cos_d0 * cos_d * math.cos(d_ra)
        k = 2.0 / (1.0 + cos_c)
        return (k * cos_d * math.sin(d_ra),
                k * (cos_d0 * sin_d - sin_d0 * cos_d * math.cos(d_ra)))

    pts = []
    for s in stars:
        px, py = project(s["ra"], s["dec"])
        pts.append({"px": px, "py": py, "mag": s["mag"], "hip": s["hip"], "star": s})

    xs = [p["px"] for p in pts]
    ys = [p["py"] for p in pts]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = (x_max - x_min) or 1.0
    y_span = (y_max - y_min) or 1.0

    # Derive any missing dimension from the figure's on-screen aspect ratio
    # (columns:rows). The projection is isotropic, so one scale serves both
    # axes; cells are ~cell_aspect taller than wide, hence the column stretch.
    both_given = width is not None and height is not None
    aspect = (x_span * cell_aspect) / y_span  # desired cols per row
    if width is None and height is None:
        width = 80
    if width is None:
        width = max(1, round(height * aspect))
    if height is None:
        height = max(1, round(width / aspect))

    # Which dimension binds (smaller scale wins). When width binds the figure
    # fills the width and there's vertical slack; when height binds, horizontal.
    scale_w = (width - 1) / (x_span * cell_aspect)
    scale_h = (height - 1) / y_span
    width_limited = scale_w <= scale_h
    scale = min(scale_w, scale_h)
    if auto_mag:
        lim = auto_mag_limit(math.degrees(1 / scale))
        pts = [p for p in pts if p["star"]["figure"] or p["mag"] <= lim]

    grid = [[" "] * width for _ in range(height)]
    used_w = x_span * scale * cell_aspect
    used_h = y_span * scale
    off_x = (width - 1 - used_w) / 2
    off_y = (height - 1 - used_h) / 2

    def to_cell(px, py):
        # East is positive px but sky charts run east-to-left: flip x.
        col = off_x + (x_max - px) * scale * cell_aspect
        row = off_y + (y_max - py) * scale
        return int(round(col)), int(round(row))

    # Grey shading on a fixed absolute scale: magnitude 0 and brighter is
    # white, each magnitude fainter is GREY_PER_MAG darker. Independent of the
    # constellation and of --maglimit, so a field of faint stars stays faint.
    def paint(glyph, mag):
        if not color:
            return glyph
        return _grey(255 - GREY_PER_MAG * mag) + glyph + RESET

    line_glyph_color = (lambda g: _grey(LINE_GREY) + g + RESET) if color else (lambda g: g)

    # Draw connecting lines first so stars are painted on top of them.
    if lines:
        cells = {p["hip"]: to_cell(p["px"], p["py"]) for p in pts if p["hip"] is not None}
        for poly in lines:
            for a, b in zip(poly, poly[1:]):
                if a in cells and b in cells:
                    (c0, r0), (c1, r1) = cells[a], cells[b]
                    glyph = line_glyph_color(_line_glyph(c1 - c0, r1 - r0))
                    _draw_segment(grid, c0, r0, c1, r1, glyph)

    # Plot brightest stars last so they win pixel collisions.
    for p in sorted(pts, key=lambda p: -p["mag"]):
        c, r = to_cell(p["px"], p["py"])
        if 0 <= r < height and 0 <= c < width:
            grid[r][c] = paint(glyph_for_mag(p["mag"]), p["mag"])

    # Planets sit on top of everything; keep those that land within the field.
    gmap = PLANET_SYMBOL if symbols else PLANET_GLYPH
    drawn = []
    for pl in planets or []:
        px, py = project(pl["ra"], pl["dec"])
        c, r = to_cell(px, py)
        if 0 <= r < height and 0 <= c < width:
            glyph = gmap.get(pl["name"], "o")
            if color:
                glyph = _rgb(*PLANET_COLOR[pl["name"]]) + glyph + RESET
            grid[r][c] = glyph
            drawn.append(pl["name"])

    rows = ["".join(line) for line in grid]
    if both_given and not width_limited:
        # Height binds; width has slack -> keep full width so the figure is
        # padded on both sides (it's already centred via off_x).
        art = "\n".join(rows)
    elif both_given:
        # Width binds; height has slack -> reduce the height by dropping the
        # blank rows the vertical centring would otherwise pad with.
        rows = [r.rstrip() for r in rows]
        lo, hi = 0, len(rows)
        while lo < hi and rows[lo] == "":
            lo += 1
        while hi > lo and rows[hi - 1] == "":
            hi -= 1
        art = "\n".join(rows[lo:hi])
    else:
        # A derived dimension already fits the figure tightly; just trim spaces.
        art = "\n".join(r.rstrip() for r in rows)
    return art, drawn, [p["star"] for p in pts]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render a star constellation as ASCII art.")
    parser.add_argument("constellation", nargs="?",
                        help="Constellation name (e.g. Orion, 'Ursa Major') or 3-letter code.")
    parser.add_argument("-m", "--maglimit", type=float, default=None,
                        help="Faintest apparent magnitude to plot (default: 4.0; with "
                             "--color, scaled to the field so wider "
                             "constellations show fewer faint stars).")
    parser.add_argument("-t", "--top", type=int, default=None,
                        help="Keep only the N brightest stars (best for a recognizable shape).")
    parser.add_argument("-w", "--width", type=int, default=None,
                        help="Canvas width. If omitted, derived from --height and the figure's "
                             "aspect ratio (or 80 if neither is given).")
    parser.add_argument("-H", "--height", type=int, default=None,
                        help="Canvas height. If omitted, derived from --width and the figure's "
                             "aspect ratio.")
    parser.add_argument("-l", "--lines", action="store_true",
                        help="Draw the constellation's connecting lines between its stars.")
    parser.add_argument("-c", "--color", "--colour", action="store_true", dest="color",
                        help="Shade stars by brightness using grey tones (bright = white).")
    parser.add_argument("-a", "--aspect", type=float, default=None,
                        help="Character cell height:width ratio. Default: ask the terminal, "
                             "falling back to 2.0. Pin this for login banners so the tool "
                             "never queries the terminal at display time.")
    parser.add_argument("-b", "--bare", action="store_true",
                        help="Print only the art (no title, legend or footer) for use as a "
                             "banner/MOTD that you compose around.")
    parser.add_argument("-p", "--planets", action="store_true",
                        help="Also plot any naked-eye planets currently within the field "
                             "(computed for the current date; unique colour each).")
    parser.add_argument("-u", "--unicode", "--symbols", action="store_true", dest="symbols",
                        help="Use astronomical symbols (☿♀♂♃♄♅♆) for planets instead of "
                             "ASCII letters. May misalign in some terminals.")
    parser.add_argument("-L", "--list", action="store_true",
                        help="List supported constellation names and exit.")
    args = parser.parse_args(argv)

    if args.list:
        for abbr in sorted(CONSTELLATIONS, key=lambda a: CONSTELLATIONS[a]):
            print(f"  {CONSTELLATIONS[abbr]:24s} ({abbr})")
        return 0
    if not args.constellation:
        parser.error("the following arguments are required: constellation")

    abbr = resolve_abbrev(args.constellation)
    if not abbr:
        sys.stderr.write(
            f"Unknown constellation: {args.constellation!r}. "
            f"Try --list to see valid names.\n")
        return 2

    polylines = asterism_lines(abbr)
    keep = {h for poly in polylines for h in poly}
    color = args.color and not os.environ.get("NO_COLOR")
    # With colour and no -m, load deep and let render() pick the limit from
    # the scale, so wide constellations don't saturate the grid.
    auto_mag = color and args.maglimit is None
    if args.maglimit is None:
        args.maglimit = AUTO_MAG_MAX if auto_mag else 4.0
    stars = load_stars(abbr, args.maglimit, args.top, keep)
    if not stars:
        sys.stderr.write(
            f"No stars found for {CONSTELLATIONS[abbr]} brighter than "
            f"magnitude {args.maglimit}. Try raising --maglimit.\n")
        return 1

    cell_aspect = args.aspect if args.aspect else detect_cell_aspect()
    planets = compute_planets() if args.planets else None

    art, drawn, stars = render(stars, args.width, args.height,
                               lines=polylines if args.lines else None,
                               cell_aspect=cell_aspect, color=color,
                               planets=planets, symbols=args.symbols,
                               auto_mag=auto_mag)

    if args.bare:
        print(art)
        return 0

    brightest = min(stars, key=lambda s: s["mag"])
    n_fig = sum(1 for s in stars if s["figure"])
    title = f"{CONSTELLATIONS[abbr]}  ({len(stars)} stars, {n_fig} in figure)"
    print(title)
    print("=" * len(title))
    print(art)
    print()
    print("Legend: @ <=1  O <=2  * <=3  + <=4  . fainter   (brighter = denser)")
    label = brightest["name"] or "brightest"
    print(f"Brightest: {label} (mag {brightest['mag']:.2f})")
    if args.planets:
        if drawn:
            gmap = PLANET_SYMBOL if args.symbols else PLANET_GLYPH
            items = []
            for name in drawn:
                g = gmap[name]
                if color:
                    g = _rgb(*PLANET_COLOR[name]) + g + RESET
                items.append(f"{g} {name}")
            print("Planets in view: " + "   ".join(items))
        else:
            print(f"Planets: none currently within {CONSTELLATIONS[abbr]}'s field")
    return 0


if __name__ == "__main__":
    sys.exit(main())

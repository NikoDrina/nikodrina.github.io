#!/usr/bin/env python3
"""Builds Campaign/SerbiaData.swift: the hex map of the third campaign, Karađorđe's Serbia from the end of 1806 to
1813 and the Ottoman lands round it, from Sarajevo and Tuzla in Bosnia to Vidin on the Danube, and from the Sava and the
Danube down to Peć, Priština and Vranje, in hexes of 4 km (see "The third campaign" in the design doc).

It is made the way make_district.py makes the pashaluk's map. Heights come from SRTM (90 m, through the OpenTopoData
API); rivers and towns from OpenStreetMap (through the Overpass API). Forest, fields, orchards and meadows are not in any
survey of the time, so they are modelled: oak and beech forest on the hills and mountains, open land in the broad valleys
and plains (Mačva, the Morava, the Kosovo field), and fields and orchards round the towns. The places are chosen by hand
(see PLACES): the nahija towns of Revolutionary Serbia and of the six nahijas it held beyond the pashaluk, the Ottoman
towns round it, and the villages where the fighting of 1806–1813 happened. Who holds each at the start is in
SerbiaStart.swift.

Run from the repository root:

    python3 Tools/district/make_serbia.py

Downloads are cached in Tools/district/cache-serbia, so later runs only redo the classification.
"""
import json
import math
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache-serbia")
OUT = os.path.join(HERE, "..", "..", "Broba pod sljivom", "Campaign", "SerbiaData.swift")
AGENT = {"User-Agent": "BorbaPodSljivom-mapbuild/0.1"}

# The map: longitude 18.05–23.25 E, from latitude 45.05 N over the Sava and the Danube down to about 42.45 N below Peć,
# Priština and Vranje. LAT0 only bounds the downloads; the grid's shape sets the true south edge.
LON0, LON1, LAT0, LAT1 = 18.05, 23.25, 42.43, 45.05
# 104 × 83 hexes of about 4 km.
COLS, ROWS = 104, 83
# The land is modelled in hexes as on the pashaluk's map (make_district.py's SCALE), so patches of forest, clearings and
# the spacing of crossings are the size on the map they are there, though each hex here is 4 km rather than 2.5.
SCALE = 2
ROW_STEP = math.sqrt(3) / 2      # pointy-top hexes, one unit wide
RADIUS = 1 / math.sqrt(3)        # centre to corner
WIDTH = COLS + 0.5
HEIGHT = (ROWS - 1) * ROW_STEP + 2 * RADIUS
KM_PER_LON = 111.32 * math.cos(math.radians((LAT0 + LAT1) / 2))
KM_PER_UNIT = (LON1 - LON0) * KM_PER_LON / WIDTH
UNITS_PER_LAT = 111.13 / KM_PER_UNIT
assert LAT1 - HEIGHT / UNITS_PER_LAT >= LAT0, "the map runs south of the downloaded box"
# About two survey points a hex, as on the pashaluk's map.
DEM_W, DEM_H = 210, 145

# Rivers an army cannot wade; upstream of the stretch given they are creeks. The Kolubara is a river from below Valjevo.
MAJOR_RIVERS = {
    "Sava": lambda lat, lon: True,
    "Dunav": lambda lat, lon: True,
    "Drina": lambda lat, lon: True,
    "Bosna": lambda lat, lon: True,
    "Lim": lambda lat, lon: True,
    "Velika Morava": lambda lat, lon: True,
    "Zapadna Morava": lambda lat, lon: True,
    "Južna Morava": lambda lat, lon: True,
    "Ibar": lambda lat, lon: lat >= 42.85,
    "Timok": lambda lat, lon: True,
    "Nišava": lambda lat, lon: True,
    "Beli Drim": lambda lat, lon: True,
    "Kolubara": lambda lat, lon: lon >= 19.95,
}
# The border rivers: Austria lies over the Sava and the Danube, and Wallachia over the Danube below the Iron Gates. They
# have no bridge or ford.
BORDER_RIVERS = {"Sava", "Dunav"}
# Named rivers shorter than this on the map are left out: across a map this size the survey names hundreds of brooks, and
# at 4 km a hex they would run wet meadow through every valley.
MIN_CREEK_KM = 25

# The ground: a hex is a mountain where the land rises steeply within it, or where it stands very high; hilly where it is
# high or uneven. Heights alone would make mountains of high plateaus, the Pešter round Sjenica and Zlatibor, which were
# open pasture; the steepness, the difference in height across the hex, is what makes a mountain.
MOUNTAIN_RELIEF, MOUNTAIN_HIGH, MOUNTAIN_HIGH_RELIEF = 420, 1350, 230
HILLY_HEIGHT, HILLY_RELIEF = 700, 150
# The share of the land outside the towns' clearings under forest.
FOREST_SHARE = 0.5

# The places, chosen by hand: name in the game, the place it stands at in OpenStreetMap (searched near the given latitude
# and longitude), the seat it belongs to, and what it is: the town (Belgrade), a nahija town, or a village under one.
PLACES = [
    # name, OSM name, lat, lon, seat, kind
    # Belgrade, the seat of the Governing Council from 1807.
    ("Belgrade", "Beograd", 44.817, 20.457, None, "town"),
    # The nahijas of the pashaluk.
    ("Šabac", "Šabac", 44.753, 19.693, None, "nahija"),
    ("Valjevo", "Valjevo", 44.271, 19.890, None, "nahija"),
    ("Smederevo", "Smederevo", 44.664, 20.927, None, "nahija"),
    ("Požarevac", "Požarevac", 44.620, 21.183, None, "nahija"),
    # Sokol, the fortress over the Drina gorge, at the village below it: the Ottomans held it through the uprising.
    ("Sokol", "Sokolac", 44.260, 19.434, None, "nahija"),
    ("Užice", "Užice", 43.858, 19.842, None, "nahija"),
    ("Čačak", "Čačak", 43.891, 20.350, None, "nahija"),
    ("Rudnik", "Rudnik", 44.137, 20.513, None, "nahija"),
    ("Kragujevac", "Kragujevac", 44.012, 20.911, None, "nahija"),
    ("Jagodina", "Jagodina", 43.977, 21.256, None, "nahija"),
    ("Ćuprija", "Ćuprija", 43.927, 21.370, None, "nahija"),
    # Poreč on the Danube, whose old town is now under the water of the Iron Gates; the nahija's place is Donji Milanovac.
    ("Poreč", "Donji Milanovac", 44.465, 22.152, None, "nahija"),
    # The six nahijas beyond the pashaluk that Revolutionary Serbia held: Krajina, Crna Reka, Paraćin, Kruševac, Stari
    # Vlah, and Podrinje, Jadar and Rađevina on the Drina.
    ("Negotin", "Negotin", 44.226, 22.531, None, "nahija"),
    ("Zaječar", "Zaječar", 43.904, 22.274, None, "nahija"),
    ("Paraćin", "Paraćin", 43.860, 21.408, None, "nahija"),
    ("Kruševac", "Kruševac", 43.580, 21.334, None, "nahija"),
    ("Stari Vlah", "Ivanjica", 43.581, 20.229, None, "nahija"),
    ("Loznica", "Loznica", 44.533, 19.223, None, "nahija"),
    ("Rađevina", "Krupanj", 44.366, 19.362, None, "nahija"),
    # Ottoman towns and fortresses round it. Bosnia over the Drina.
    ("Sarajevo", "Sarajevo", 43.856, 18.413, None, "nahija"),
    ("Tuzla", "Tuzla", 44.538, 18.676, None, "nahija"),
    ("Bijeljina", "Bijeljina", 44.757, 19.214, None, "nahija"),
    ("Zvornik", "Zvornik", 44.386, 19.102, None, "nahija"),
    # Up the Drina toward Sarajevo the game names places the 1990s did not make bywords. Osat, the old district on the
    # Drina's left bank that the Ottomans folded into the Sanjak of Zvornik, at its town; Dobrun, the village and
    # monastery in the Rzav gorge where the road from Užice comes down to the Drina; and Čajniče, between the Drina and
    # Pljevlja. Until November 2026 they were Srebrenica, Višegrad and Foča.
    ("Osat", "Srebrenica", 44.106, 19.297, None, "nahija"),
    ("Dobrun", "Donji Dobrun", 43.763, 19.388, None, "nahija"),
    ("Čajniče", "Čajniče", 43.557, 19.072, None, "nahija"),
    # The Sanjak of Novi Pazar and the Lim.
    ("Pljevlja", "Pljevlja", 43.357, 19.359, None, "nahija"),
    ("Prijepolje", "Prijepolje", 43.390, 19.648, None, "nahija"),
    ("Nova Varoš", "Nova Varoš", 43.461, 19.813, None, "nahija"),
    ("Sjenica", "Sjenica", 43.273, 20.000, None, "nahija"),
    ("Bijelo Polje", "Bijelo Polje", 43.038, 19.747, None, "nahija"),
    ("Novi Pazar", "Novi Pazar", 43.137, 20.512, None, "nahija"),
    # Kosovo.
    ("Mitrovica", "Kosovska Mitrovica", 42.890, 20.866, None, "nahija"),
    ("Vučitrn", "Vushtrri", 42.823, 20.968, None, "nahija"),
    ("Priština", "Priština", 42.663, 21.164, None, "nahija"),
    ("Peć", "Peć", 42.659, 20.288, None, "nahija"),
    # Niš and the south: the Constantinople road from Niš by Pirot to Sofia.
    ("Niš", "Niš", 43.321, 21.896, None, "nahija"),
    ("Aleksinac", "Aleksinac", 43.541, 21.707, None, "nahija"),
    ("Prokuplje", "Prokuplje", 43.234, 21.588, None, "nahija"),
    ("Kuršumlija", "Kuršumlija", 43.140, 21.273, None, "nahija"),
    ("Leskovac", "Leskovac", 42.998, 21.946, None, "nahija"),
    ("Vranje", "Vranje", 42.551, 21.900, None, "nahija"),
    ("Pirot", "Pirot", 43.153, 22.586, None, "nahija"),
    # Vidin's pashaluk, and Kladovo, the Ottoman fortress of Fetislam on the Danube.
    ("Vidin", "Vidin", 43.990, 22.873, None, "nahija"),
    ("Belogradčik", "Belogradčik", 43.627, 22.684, None, "nahija"),
    ("Kladovo", "Kladovo", 44.607, 22.611, None, "nahija"),
    # Villages: Karađorđe's Topola, fortified as his seat; the Constantinople road at Palanka; the Drina valley and the
    # Morava valley; Deligrad's lines on the road to Niš (1806–1813); Varvarin, where the Russians and Serbs beat the
    # Ottomans in 1810; Štubik in the Krajina, where they fought together in 1807; and Gurgusovac (Knjaževac) on the Timok.
    ("Topola", "Topola", 44.255, 20.682, "Kragujevac", "village"),
    ("Palanka", "Smederevska Palanka", 44.365, 20.958, "Smederevo", "village"),
    ("Bajina Bašta", "Bajina Bašta", 43.971, 19.566, "Užice", "village"),
    ("Požega", "Požega", 43.846, 20.036, "Užice", "village"),
    ("Karanovac", "Kraljevo", 43.725, 20.687, "Čačak", "village"),
    ("Deligrad", "Deligrad", 43.623, 21.594, "Paraćin", "village"),
    ("Varvarin", "Varvarin", 43.722, 21.367, "Kruševac", "village"),
    ("Štubik", "Štubik", 44.302, 22.357, "Negotin", "village"),
    ("Gurgusovac", "Knjaževac", 43.567, 22.257, "Zaječar", "village"),
    ("Raška", "Raška", 43.286, 20.613, "Novi Pazar", "village"),
]

# Cyrillic to the Latin of the game, for names the survey gives only in Serbian or Bulgarian Cyrillic.
CYRILLIC = dict(zip("абвгдђежзијклљмнњопрстћуфхцчџшйщъьюя",
                    ["a", "b", "v", "g", "d", "đ", "e", "ž", "z", "i", "j", "k", "l", "lj", "m", "n", "nj", "o", "p", "r",
                     "s", "t", "ć", "u", "f", "h", "c", "č", "dž", "š", "j", "št", "a", "", "ju", "ja"]))
# Names the survey gives a river in another tongue, where it runs outside Serbia.
ALIASES = {"Danube": "Dunav", "Dunărea": "Dunav", "Donau": "Dunav", "Duna": "Dunav"}


def latin(s):
    out = ""
    for ch in s:
        low = ch.lower()
        if low in CYRILLIC:
            t = CYRILLIC[low]
            out += t.capitalize() if ch != low else t
        else:
            out += ch
    return out


def name_of(tags):
    for key in ("name:sr-Latn", "name:sh", "name:bs", "name:hr"):
        if tags.get(key):
            return ALIASES.get(tags[key], tags[key])
    if tags.get("name:sr"):
        return latin(tags["name:sr"])
    name = tags.get("name")
    if not name:
        return None
    if tags.get("name:en") in ALIASES:
        return ALIASES[tags["name:en"]]
    return ALIASES.get(name, latin(name))


def to_map(lat, lon):
    return ((lon - LON0) / (LON1 - LON0) * WIDTH, (LAT1 - lat) * UNITS_PER_LAT)


def to_geo(x, y):
    return (LAT1 - y / UNITS_PER_LAT, LON0 + x / WIDTH * (LON1 - LON0))


# ---------------------------------------------------------------- downloads

def cached(name, fetch):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        # Fetched first and written after, so a failed download leaves nothing behind to be read next time.
        data = fetch()
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    with open(path) as f:
        return json.load(f)


def get(url, data=None, timeout=180):
    """A JSON download through curl: the Python that ships with Xcode is built against an old LibreSSL that some
    servers, Overpass among them, no longer shake hands with."""
    cmd = ["curl", "-sS", "--fail", "--retry", "3", "--retry-all-errors", "--retry-delay", "10", "-m", str(timeout),
           "-A", AGENT["User-Agent"], url]
    if data is not None:
        cmd += ["--data-urlencode", f"data={data}"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def overpass(query):
    return get("https://overpass-api.de/api/interpreter", data=query, timeout=300)


def fetch_dem():
    pts = []
    for j in range(DEM_H):
        lat = LAT1 - (LAT1 - LAT0) * j / (DEM_H - 1)
        for i in range(DEM_W):
            pts.append((round(lat, 5), round(LON0 + (LON1 - LON0) * i / (DEM_W - 1), 5)))
    elev = []
    for k in range(0, len(pts), 100):
        url = "https://api.opentopodata.org/v1/srtm90m?locations=" + "|".join(f"{a},{b}" for a, b in pts[k:k + 100])
        for _ in range(5):
            try:
                data = get(url, timeout=60)
                if data.get("status") == "OK":
                    elev += [r["elevation"] if r["elevation"] is not None else 0 for r in data["results"]]
                    break
            except Exception as e:  # noqa: BLE001 - retry any network hiccup
                print("retrying", k, e)
            time.sleep(3)
        else:
            raise SystemExit(f"elevation download failed at {k}")
        if k % 5000 == 0:
            print("heights", k, "of", len(pts), flush=True)
        time.sleep(1.1)
    return {"w": DEM_W, "h": DEM_H, "elev": elev}


def tiles(n_lat, n_lon):
    for a in range(n_lat):
        for b in range(n_lon):
            yield (LAT0 + (LAT1 - LAT0) * a / n_lat, LON0 + (LON1 - LON0) * b / n_lon,
                   LAT0 + (LAT1 - LAT0) * (a + 1) / n_lat, LON0 + (LON1 - LON0) * (b + 1) / n_lon)


def fetch_places():
    """Towns and villages, a quarter of the map at a time."""
    nodes = {}
    for la0, lo0, la1, lo1 in tiles(2, 2):
        part = overpass(f'[out:json][timeout:250];node["place"~"^(village|town|city)$"]({la0},{lo0},{la1},{lo1});out;')
        for el in part["elements"]:
            nodes[el["id"]] = el
        time.sleep(5)
    return {"elements": list(nodes.values())}


def fetch_rivers():
    """Named rivers, a ninth of the map at a time: the whole box at once is more than the server will answer. A way
    that crosses into two tiles comes back from both and is kept once."""
    ways = {}
    for la0, lo0, la1, lo1 in tiles(3, 3):
        part = overpass(f'[out:json][timeout:250];way["waterway"="river"]["name"]({la0},{lo0},{la1},{lo1});out geom;')
        for way in part["elements"]:
            ways[way["id"]] = way
        print("rivers", len(ways), flush=True)
        time.sleep(5)
    return {"elements": list(ways.values())}


places = cached("places.json", fetch_places)
rivers_raw = cached("rivers.json", fetch_rivers)
dem = cached("dem.json", fetch_dem)["elev"]


def elevation(x, y):
    lat, lon = to_geo(x, y)
    fi = min(DEM_W - 1.001, max(0, (lon - LON0) / (LON1 - LON0) * (DEM_W - 1)))
    fj = min(DEM_H - 1.001, max(0, (LAT1 - lat) / (LAT1 - LAT0) * (DEM_H - 1)))
    i, j = int(fi), int(fj)
    tx, ty = fi - i, fj - j
    e = lambda a, b: dem[b * DEM_W + a]
    top = e(i, j) * (1 - tx) + e(i + 1, j) * tx
    bottom = e(i, j + 1) * (1 - tx) + e(i + 1, j + 1) * tx
    return top * (1 - ty) + bottom * ty


# ---------------------------------------------------------------- hexes

def center(c, r):
    return (c + 0.5 + 0.5 * (r & 1), RADIUS + r * ROW_STEP)


def hex_at(x, y):
    px, py = x - 0.5, y - RADIUS
    q = (math.sqrt(3) / 3 * px - py / 3) / RADIUS
    r = (2 / 3 * py) / RADIUS
    cx, cz = q, r
    cy = -cx - cz
    rx, ry, rz = round(cx), round(cy), round(cz)
    dx, dy, dz = abs(rx - cx), abs(ry - cy), abs(rz - cz)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    row = rz
    return (rx + (row - (row & 1)) // 2, row)


def neighbours(c, r):
    q = c - (r - (r & 1)) // 2
    for dq, dr in ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)):
        nq, nr = q + dq, r + dr
        nc = nq + (nr - (nr & 1)) // 2
        if 0 <= nc < COLS and 0 <= nr < ROWS:
            yield (nc, nr)


def inside(c, r):
    return 0 <= c < COLS and 0 <= r < ROWS


# ---------------------------------------------------------------- noise

def hash2(i, j, seed):
    h = (i * 374761393 + j * 668265263 + seed * 982451653) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def noise(x, y, scale, seed):
    x, y = x / scale, y / scale
    i, j = math.floor(x), math.floor(y)
    fx, fy = x - i, y - j
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = hash2(i, j, seed), hash2(i + 1, j, seed)
    c, d = hash2(i, j + 1, seed), hash2(i + 1, j + 1, seed)
    return (a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- rivers

def simplify(pts, tol):
    if len(pts) < 3:
        return pts
    (ax, ay), (bx, by) = pts[0], pts[-1]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1e-9
    far, index = 0.0, 0
    for k in range(1, len(pts) - 1):
        d = abs((pts[k][0] - ax) * dy - (pts[k][1] - ay) * dx) / length
        if d > far:
            far, index = d, k
    if far <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:index + 1], tol)[:-1] + simplify(pts[index:], tol)


def join(chains):
    """Ways of one river joined end to end where they meet, by their ends."""
    chains = [list(c) for c in chains]
    key = lambda p: (round(p[0], 7), round(p[1], 7))
    merged = True
    while merged:
        merged = False
        ends = {}
        for k, ch in enumerate(chains):
            ends.setdefault(key(ch[0]), []).append((k, 0))
            ends.setdefault(key(ch[-1]), []).append((k, -1))
        for k, ch in enumerate(chains):
            for side in (-1, 0):
                for other, other_side in ends.get(key(ch[side]), []):
                    if other == k:
                        continue
                    a, b = chains[k], chains[other]
                    if side == -1 and other_side == 0:
                        chains[k] = a + b[1:]
                    elif side == -1 and other_side == -1:
                        chains[k] = a + b[::-1][1:]
                    elif side == 0 and other_side == -1:
                        chains[k] = b + a[1:]
                    else:
                        chains[k] = b[::-1] + a[1:]
                    del chains[other]
                    merged = True
                    break
                if merged:
                    break
            if merged:
                break
    return chains


def length_km(chain):
    return sum(math.hypot((a[1] - b[1]) * KM_PER_LON, (a[0] - b[0]) * 111.13) for a, b in zip(chain, chain[1:]))


by_name = {}
for way in rivers_raw["elements"]:
    name = name_of(way["tags"])
    if not name or "geometry" not in way:
        continue
    by_name.setdefault(name, []).append([(g["lat"], g["lon"]) for g in way["geometry"]])

rivers = []  # (name, major, [(x, y)])
dropped = 0
for name, ways in sorted(by_name.items()):
    for chain in join(ways):
        if name not in MAJOR_RIVERS and length_km(chain) < MIN_CREEK_KM:
            dropped += 1
            continue
        pts = [to_map(lat, lon) for lat, lon in chain]
        # Keep the parts on the map, with a little run-off past the edge.
        part = []
        for p in pts + [None]:
            if p is not None and -0.6 <= p[0] <= WIDTH + 0.6 and -0.6 <= p[1] <= HEIGHT + 0.6:
                part.append(p)
                continue
            if len(part) >= 2:
                # Split each river where it changes between creek and river.
                rule = MAJOR_RIVERS.get(name, lambda lat, lon: False)
                test = lambda x, y: rule(*to_geo(x, y))
                run = [part[0]]
                for a, b in zip(part, part[1:]):
                    if test(*a) != test(*b):
                        run.append(b)
                        rivers.append((name, test(*a), simplify(run, 0.07)))
                        run = [b]
                    else:
                        run.append(b)
                if len(run) >= 2:
                    rivers.append((name, test(*run[0]), simplify(run, 0.07)))
            part = []
print("rivers:", len(rivers), "pieces;", dropped, "short creeks left out")


def seal(rivers):
    """The border rivers as unbroken walls: pieces of one that end within three hexes of each other are joined, as where
    the survey loses the Danube among its islands, and an end that stops short of the map's edge is carried on to it."""
    out = [r for r in rivers if r[0] not in BORDER_RIVERS or not r[1]]
    for name in sorted(BORDER_RIVERS):
        pieces = [list(pts) for n, major, pts in rivers if n == name and major]
        while len(pieces) > 1:
            # The nearest pair of ends of two pieces, whichever way round they run.
            best = None
            for i in range(len(pieces)):
                for j in range(len(pieces)):
                    if i == j:
                        continue
                    for flip_i in (False, True):
                        for flip_j in (False, True):
                            a = pieces[i][::-1] if flip_i else pieces[i]
                            b = pieces[j][::-1] if flip_j else pieces[j]
                            d = math.dist(a[-1], b[0])
                            if best is None or d < best[0]:
                                best = (d, i, j, a, b)
            d, i, j, a, b = best
            if d > 3:
                break
            pieces = [p for k, p in enumerate(pieces) if k not in (i, j)] + [a + b]
        for pts in pieces:
            for k in (0, -1):
                x, y = pts[k]
                gap, point = min([(x, (-0.6, y)), (WIDTH - x, (WIDTH + 0.6, y)), (y, (x, -0.6)), (HEIGHT - y, (x, HEIGHT + 0.6))],
                                 key=lambda e: e[0])
                if 0 < gap <= 2.5:
                    if k == 0:
                        pts.insert(0, point)
                    else:
                        pts.append(point)
            out.append((name, True, pts))
    return out


rivers = seal(rivers)


def raster(pts):
    cells = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        steps = max(1, int(math.hypot(bx - ax, by - ay) / 0.05))
        for k in range(steps + 1):
            t = k / steps
            h = hex_at(ax + (bx - ax) * t, ay + (by - ay) * t)
            if inside(*h) and (not cells or cells[-1] != h):
                cells.append(h)
    return cells


def distance_to(pts_list, x, y):
    best = 1e9
    for pts in pts_list:
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, by - ay
            t = clamp(((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1e-9))
            best = min(best, math.hypot(ax + dx * t - x, ay + dy * t - y))
    return best


# ---------------------------------------------------------------- settlements

def km(a, b):
    return math.hypot((a[1] - b[1]) * KM_PER_LON, (a[0] - b[0]) * 111.13)


def steps(a, b):
    qa, qb = a[0] - (a[1] - (a[1] & 1)) // 2, b[0] - (b[1] - (b[1] & 1)) // 2
    dq, dr = qa - qb, a[1] - b[1]
    return max(abs(dq), abs(dr), abs(dq + dr))


survey = []
for el in places["elements"]:
    name = name_of(el.get("tags", {}))
    if name:
        survey.append({"name": name, "place": el["tags"].get("place"), "lat": el["lat"], "lon": el["lon"]})

# Each place stands where the survey puts the place of its name nearest the given point, within 15 km; one that is not
# found stops the build with the places around the point to choose from instead.
chosen = []
missing = []
for name, osm, lat, lon, parent, kind in PLACES:
    near = sorted((km((s["lat"], s["lon"]), (lat, lon)), s["name"], s) for s in survey)
    found = [(d, s) for d, n, s in near if n == osm and d <= 15]
    if not found:
        around = ", ".join(f"{n} ({s['place']}, {d:.1f} km)" for d, n, s in near[:10])
        missing.append(f"{name}: no {osm!r} within 15 km of {lat}, {lon}. Near there: {around}")
        continue
    s = found[0][1]
    x, y = to_map(s["lat"], s["lon"])
    if not (0.7 * SCALE <= x <= WIDTH - 0.7 * SCALE and 0.7 * SCALE <= y <= HEIGHT - 0.7 * SCALE):
        raise SystemExit(f"{name} ({osm}) lies too near the edge of the map, at {x:.1f}, {y:.1f}")
    chosen.append({"name": name, "kind": kind, "parent": parent, "lat": s["lat"], "lon": s["lon"], "at": (x, y),
                   "hex": hex_at(x, y)})
if missing:
    raise SystemExit("\n".join(missing))
counts = {c["name"]: sum(1 for o in chosen if o["parent"] == c["name"]) for c in chosen if not c["parent"]}

# ---------------------------------------------------------------- terrain

major = [pts for name, is_major, pts in rivers if is_major]
minor = [pts for name, is_major, pts in rivers if not is_major]
river_hexes, stream_hexes, border_hexes = set(), set(), set()
river_paths = [(name, raster(pts)) for name, is_major, pts in rivers if is_major]
for name, path in river_paths:
    river_hexes.update(path)
    if name in BORDER_RIVERS:
        border_hexes.update(path)
for p in minor:
    stream_hexes.update(raster(p))

# A town on a border river stands on its own bank: Belgrade, Smederevo and Vidin look over the water at Austria or
# Wallachia, and a settlement in the river's own hex would be a way across it. It moves to the dry neighbour nearest
# where it really stands, which is on its own bank.
for c in chosen:
    if c["hex"] in border_hexes:
        others = [o["hex"] for o in chosen if o is not c]
        dry = [n for n in neighbours(*c["hex"]) if n not in river_hexes and n not in others]
        assert dry, c["name"]
        c["hex"] = min(dry, key=lambda n: math.dist(center(*n), c["at"]))
        print("moved to the bank:", c["name"], c["hex"])
# Places stand at least two hexes apart, so an army at one is never taken for being at its neighbour.
close = [f"{a['name']} and {b['name']} ({steps(a['hex'], b['hex'])})" for i, a in enumerate(chosen) for b in chosen[i + 1:]
         if steps(a["hex"], b["hex"]) < 2]
if close:
    raise SystemExit("too close: " + "; ".join(close))
settlement_hexes = {c["hex"]: c for c in chosen}
settlement_pts = [center(*c["hex"]) for c in chosen]

info = {}
for r in range(ROWS):
    for c in range(COLS):
        x, y = center(c, r)
        samples = [elevation(x, y)] + [elevation(x + 0.42 * math.cos(a), y + 0.42 * math.sin(a)) for a in [k * math.pi / 3 + math.pi / 6 for k in range(6)]]
        e = samples[0]
        relief = max(samples) - min(samples)
        d_place = min(math.hypot(x - px, y - py) for px, py in settlement_pts)
        d_major = distance_to(major, x, y)
        wild = 0.6 * noise(x, y, 4.5 * SCALE, 11) + 0.4 * noise(x, y, 1.7 * SCALE, 23)
        # Forest on the slopes, open land on the flat: the broad valleys and plains were farmed and grazed, high ones as
        # much as low, the Kosovo field and Metohija as much as Mačva. Steepness counts for the woods, height hardly.
        score = (wild + 0.12 * clamp((e - 300) / 1200) + 0.55 * clamp(relief / 300)
                 - 0.95 * clamp(1 - d_place / (1.6 * SCALE)) - 0.3 * clamp(1 - d_major / (1.2 * SCALE)))
        info[(c, r)] = (e, relief, d_place, score)


def mountainous(e, relief):
    return relief >= MOUNTAIN_RELIEF or (e >= MOUNTAIN_HIGH and relief >= MOUNTAIN_HIGH_RELIEF)


def is_hilly(e, relief):
    """Uneven ground, or high ground that is not quite flat; a high plain, as the Kosovo field, is not hilly."""
    return relief >= HILLY_RELIEF or (e >= HILLY_HEIGHT and relief >= 70) or e >= 1000


open_scores = sorted(s for h, (e, rel, d, s) in info.items()
                     if h not in river_hexes and not mountainous(e, rel) and d > 1.05 * SCALE * 0.8)
FOREST_LINE = open_scores[int(len(open_scores) * (1 - FOREST_SHARE))]

terrain = {}
for (c, r), (e, relief, d_place, score) in info.items():
    x, y = center(c, r)
    pick = noise(x, y, 1.3 * SCALE, 37)
    hilly = is_hilly(e, relief)
    if (c, r) in river_hexes:
        t = "~"
    elif mountainous(e, relief) and (c, r) not in settlement_hexes:
        t = "M"
    elif (c, r) in settlement_hexes:
        t = "o" if pick < 0.45 else "w"
    elif d_place <= 0.85 * SCALE:
        # Next to the houses: plum orchards on the slopes, fields, the rest pasture.
        t = "o" if pick < 0.38 and e > 150 else "w" if pick < 0.66 else "h" if hilly else "."
    elif score > FOREST_LINE:
        t = "F" if hilly else "f"
    elif relief < 80 and e < 750 and pick > 0.5:
        # The farmed plains: Mačva, Posavina, the Morava, the Kosovo field and Metohija.
        t = "w"
    else:
        t = "h" if hilly else "."
    # Creeks keep a strip of wet meadow through open land; in the forest they stay under the trees.
    if (c, r) in stream_hexes and t in ".who":
        t = "s"
    terrain[(c, r)] = t

# Passes: mountain hexes a road crossed, left as wooded hills so the land beyond is not cut off.
PASSES = {}
for h, t in PASSES.items():
    assert terrain[h] == "M", f"the pass at {h} is no longer a mountain hex: {terrain[h]}"
    terrain[h] = t

# Crossings: a bridge or ford every few hexes along the big rivers, and wherever a settlement stands by the water; none
# over the border rivers.
seat_hexes = {c["hex"] for c in chosen if not c["parent"]}
for name, path in river_paths:
    if name in BORDER_RIVERS:
        continue
    since = 99
    for h in path:
        since += 1
        # Where a river runs into the Sava or the Danube its last hexes are the border river's too, and a ford there
        # would stand in the border river: the Drina's put one in the Sava at its mouth.
        if h in border_hexes:
            continue
        if h in settlement_hexes:
            terrain[h] = "b"
            since = 0
            continue
        if terrain[h] != "~":
            since = 0
            continue
        near = [s for s in settlement_hexes if math.dist(center(*s), center(*h)) <= 1.05 * SCALE]
        dry = [n for n in neighbours(*h) if terrain.get(n) not in ("~", "=", "b")]
        if len(dry) < 2:
            continue
        if (near and since >= 3 * SCALE) or since >= 7 * SCALE:
            terrain[h] = "b" if any(s in seat_hexes for s in near) else "="
            since = 0

# ---------------------------------------------------------------- what the villages live off


def within(h, k):
    return [(c, r) for r in range(h[1] - k, h[1] + k + 1) for c in range(h[0] - k - 1, h[0] + k + 2)
            if inside(c, r) and steps((c, r), h) <= k]


def hilly(h):
    return is_hilly(info[h][0], info[h][1])


def trade_of(h):
    """What a village lives off: the land within three hexes of it, its fields, orchards and meadows and the edge of the
    woods. Each kind of ground counts toward its trade and the most wins; the woods count more, since they begin only
    where the village's clearing ends. Mountains close by make it a mining village."""
    if sum(terrain[x] == "M" for x in within(h, 2)) >= 2:
        return "iron"
    near = {}
    for x in within(h, 3):
        near[terrain[x]] = near.get(terrain[x], 0) + 1
    n = lambda chars: sum(near.get(ch, 0) for ch in chars)
    scores = [("grain", n("w")), ("plums", n("o") * 1.2), ("livestock", n(".hs") * 0.9), ("wood", n("fF") * 1.6)]
    return max(scores, key=lambda s: s[1])[0]  # the first of equal scores wins


TRADE = {"Bajina Bašta": "wood"}

villages = [c for c in chosen if c.get("parent")]
for c in villages:
    c["trade"] = TRADE.get(c["name"]) or trade_of(c["hex"])

rows = ["".join(terrain[(c, r)] for c in range(COLS)) for r in range(ROWS)]

# ---------------------------------------------------------------- checks

# Every place can be reached from Belgrade over land an army can cross: no mountains, and rivers only at their crossings.
start = next(c["hex"] for c in chosen if c["name"] == "Belgrade")
seen, todo = {start}, [start]
while todo:
    h = todo.pop()
    for n in neighbours(*h):
        if n not in seen and terrain[n] not in "M~":
            seen.add(n)
            todo.append(n)
cut_off = [c["name"] for c in chosen if c["hex"] not in seen]

# And the border rivers close off Austria and Wallachia: from Belgrade, over everything but them, no step reaches Srem,
# the Banat, or the Wallachian bank opposite Vidin.
seen_land, todo = {start}, [start]
while todo:
    h = todo.pop()
    for n in neighbours(*h):
        if n not in seen_land and n not in border_hexes:
            seen_land.add(n)
            todo.append(n)
beyond = {"Srem": (44.98, 19.40), "the Banat": (44.95, 21.00), "Wallachia": (44.10, 23.10)}
leaks = [name for name, (lat, lon) in beyond.items() if hex_at(*to_map(lat, lon)) in seen_land]
if leaks:
    raise SystemExit("the border rivers let the land through to " + ", ".join(leaks))

# ---------------------------------------------------------------- output

for r, row in enumerate(rows):
    print(("  " if r & 1 else "") + " ".join(row))
tally = {}
for row in rows:
    for ch in row:
        tally[ch] = tally.get(ch, 0) + 1
print(tally, len(chosen), "settlements", counts)
print("cut off from Belgrade:", cut_off or "none")
heights = sorted(e for e, rel, d, s in info.values())
reliefs = sorted(rel for e, rel, d, s in info.values())
print("heights (10/50/90/99%):", [round(heights[int(len(heights) * p)]) for p in (0.1, 0.5, 0.9, 0.99)],
      "relief:", [round(reliefs[int(len(reliefs) * p)]) for p in (0.1, 0.5, 0.9, 0.99)])


def q(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


lines = [
    "//",
    "//  SerbiaData.swift",
    "//  Broba pod sljivom",
    "//",
    "//  Generated by Tools/district/make_serbia.py; edit that script, not this file.",
    "//  Heights: SRTM 90 m via OpenTopoData. Rivers and towns: © OpenStreetMap contributors (ODbL).",
    "//",
    "",
    "import Foundation",
    "",
    "/// The third campaign's map: Karađorđe's Serbia, 1806–1813, and the Ottoman lands round it, in hexes of 4 km.",
    "nonisolated enum SerbiaData {",
    f"    static let cols = {COLS}",
    f"    static let rows = {ROWS}",
    f"    static let kmPerHex = {KM_PER_UNIT:.3f}",
    "",
    "    /// Terrain of each hex, row by row from the north; odd rows sit half a hex to the east.",
    "    /// . meadow  w fields  o plum orchards  f oak forest  F forested hills  h open hills  M mountain",
    "    /// s stream  ~ river  = ford  b bridge",
    "    static let terrain: [String] = [",
]
lines += [f'        "{row}",' for row in rows]
lines += [
    "    ]",
    "",
    "    /// Heights in metres on a regular grid over the map, row by row from the north edge.",
    f"    static let heightGrid = (width: {DEM_W}, height: {DEM_H}, lon: ({LON0}, {LON1}), lat: ({LAT0}, {LAT1}))",
    f"    static let mapLon = ({LON0}, {LON1})",
    f"    static let mapLatTop = {LAT1}",
    f"    static let hexesPerDegreeLat = {UNITS_PER_LAT:.4f}",
    "    static let heights = \"\"\"",
]
for j in range(DEM_H):
    lines.append("        " + ",".join(str(int(round(v))) for v in dem[j * DEM_W:(j + 1) * DEM_W]) + ("," if j < DEM_H - 1 else ""))
lines += [
    "        \"\"\"",
    "",
    "    /// River courses in map units (one unit is a hex's width), as x, y pairs.",
    "    static let rivers: [(name: String, major: Bool, points: [Double])] = [",
]
for name, is_major, pts in rivers:
    flat = ", ".join(f"{q(x)}, {q(y)}" for x, y in pts)
    lines.append(f'        ("{name}", {"true" if is_major else "false"}, [{flat}]),')
lines += [
    "    ]",
    "",
    "    /// The towns and the villages under them: name, hex column and row, the town a village belongs to, what it lives",
    "    /// off (a town's trade is set in the game), and what it is: town, nahija or village.",
    "    static let places: [(name: String, col: Int, row: Int, parent: String?, trade: String?, kind: String)] = [",
]
for c in chosen:
    parent = f'"{c["parent"]}"' if c.get("parent") else "nil"
    trade = f'"{c["trade"]}"' if c.get("trade") else "nil"
    lines.append(f'        ("{c["name"]}", {c["hex"][0]}, {c["hex"][1]}, {parent}, {trade}, "{c["kind"]}"),')
lines += ["    ]", "}", ""]
if cut_off:
    raise SystemExit("not written: places cut off from Belgrade: " + ", ".join(cut_off))
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("wrote", os.path.normpath(OUT))

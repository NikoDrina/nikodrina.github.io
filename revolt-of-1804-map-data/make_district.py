#!/usr/bin/env python3
"""Builds Campaign/DistrictData.swift: the hex map of the Belgrade pashaluk as it might have looked in 1804, from
Šabac to Požarevac and from Belgrade to Kragujevac and Jagodina.

Heights come from SRTM (90 m, through the OpenTopoData API); rivers and villages from OpenStreetMap
(through the Overpass API). Forest, fields, orchards and meadows are not in any survey of 1804, so they are
modelled: Šumadija was still mostly oak forest, with fields and plum orchards in clearings around the villages
and wet meadows along the rivers. What each village lives off is read from the land around it, and its clearing is
then shaped to show it. The places are chosen by hand (see PLACES): the nahija towns, their knežine, and the villages
where the fighting of 1804–1806 happened.

Run from the repository root:

    python3 Tools/district/make_district.py

Downloads are cached in Tools/district/cache, so later runs only redo the classification.
"""
import json
import math
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "..", "..", "Broba pod sljivom", "Campaign", "DistrictData.swift")
AGENT = {"User-Agent": "BorbaPodSljivom-mapbuild/0.1"}

# The map: longitude 19.35–21.50 E, from latitude 44.92 N on the Sava and the Danube down to about 43.78 N below
# Kragujevac and Jagodina. LAT0 only bounds the downloads; the grid's shape sets the true south edge.
LON0, LON1, LAT0, LAT1 = 19.35, 21.50, 43.76, 44.92
# Hexes per 1.7 km of the first map: the grid was 34 × 29 hexes of 1.7 km; at 2 it is 68 × 58 hexes. The map has since
# grown to the pashaluk at about 2.5 km a hex, but the land is still modelled in hexes, so patches of forest, clearings
# and the spacing of crossings keep the size on the map they had.
SCALE = 2
COLS, ROWS = 34 * SCALE, 29 * SCALE
ROW_STEP = math.sqrt(3) / 2      # pointy-top hexes, one unit wide
RADIUS = 1 / math.sqrt(3)        # centre to corner
WIDTH = COLS + 0.5
HEIGHT = (ROWS - 1) * ROW_STEP + 2 * RADIUS
KM_PER_LON = 111.32 * math.cos(math.radians((LAT0 + LAT1) / 2))
KM_PER_UNIT = (LON1 - LON0) * KM_PER_LON / WIDTH
UNITS_PER_LAT = 111.13 / KM_PER_UNIT
assert LAT1 - HEIGHT / UNITS_PER_LAT >= LAT0, "the map runs south of the downloaded box"
DEM_W, DEM_H = 128, 96

# Rivers an army cannot wade, with the stretch where each becomes one; upstream they are creeks. The Kolubara is a river
# from below Valjevo.
MAJOR_RIVERS = {
    "Sava": lambda lat, lon: True,
    "Dunav": lambda lat, lon: True,
    "Drina": lambda lat, lon: True,
    "Velika Morava": lambda lat, lon: True,
    "Zapadna Morava": lambda lat, lon: True,
    "Kolubara": lambda lat, lon: lon >= 19.95,
}
# The border rivers: Austria lies over the Sava and the Danube, Bosnia over the Drina. They have no bridge or ford.
BORDER_RIVERS = {"Sava", "Dunav", "Drina"}

# The places, chosen by hand: name in the game, the place it stands at in OpenStreetMap (searched near the given
# latitude and longitude), the seat it belongs to, and what it is: the town (Belgrade), a nahija town, a knežina or a
# village. The nine nahija towns and Orašac, seat of the Jasenica knežina, are the seats; under each stand its knežine,
# at their chief village, and the villages of the fighting of 1804–1806.
PLACES = [
    # name, OSM name, lat, lon, seat, kind
    ("Belgrade", "Beograd", 44.817, 20.457, None, "town"),
    ("Kragujevac", "Kragujevac", 44.012, 20.911, None, "nahija"),
    ("Rudnik", "Rudnik", 44.137, 20.513, None, "nahija"),
    ("Valjevo", "Valjevo", 44.271, 19.890, None, "nahija"),
    ("Šabac", "Šabac", 44.753, 19.693, None, "nahija"),
    ("Smederevo", "Smederevo", 44.664, 20.927, None, "nahija"),
    ("Grocka", "Grocka", 44.671, 20.717, None, "nahija"),
    ("Požarevac", "Požarevac", 44.620, 21.183, None, "nahija"),
    ("Jagodina", "Jagodina", 43.977, 21.256, None, "nahija"),
    # Sokol, the fortress over the Drina gorge, at the village below it: the Ottomans held it through the uprising.
    ("Sokol", "Sokolac", 44.260, 19.434, None, "nahija"),
    ("Orašac", "Orašac", 44.333, 20.583, None, "knezina"),
    # Belgrade nahija: the assembly by the Sava, the fights of April 1804 and the meeting with Aganlija.
    ("Ostružnica", "Ostružnica", 44.716, 20.320, "Belgrade", "village"),
    ("Leštane", "Leštane", 44.730, 20.582, "Belgrade", "village"),
    ("Ropočevo", "Ropočevo", 44.520, 20.570, "Belgrade", "village"),
    ("Drlupa", "Drlupa", 44.470, 20.520, "Belgrade", "village"),
    # Grocka nahija: the villages of the knezes Palalija and Čarapić.
    ("Begaljica", "Begaljica", 44.620, 20.650, "Grocka", "village"),
    ("Beli Potok", "Beli Potok", 44.720, 20.520, "Grocka", "village"),
    # Smederevo nahija: Hasan Pasha's Palanka, the Lipe assembly, and the Morava crossing.
    ("Palanka", "Smederevska Palanka", 44.365, 20.958, "Smederevo", "village"),
    ("Lipe", "Lipe", 44.641, 20.999, "Smederevo", "village"),
    ("Velika Plana", "Velika Plana", 44.333, 21.076, "Smederevo", "village"),
    # Požarevac nahija: its knežine west of the hills.
    ("Braničevo", "Kostolac", 44.716, 21.170, "Požarevac", "knezina"),
    ("Stig", "Malo Crniće", 44.565, 21.300, "Požarevac", "knezina"),
    ("Mlava", "Petrovac na Mlavi", 44.378, 21.418, "Požarevac", "knezina"),
    # Kragujevac nahija: Lepenica and the two Gružas, and Batočina, where the Arnauts were beaten in March 1804.
    ("Lepenica", "Badnjevac", 44.120, 20.960, "Kragujevac", "knezina"),
    ("Gornja Gruža", "Knić", 43.922, 20.719, "Kragujevac", "knezina"),
    ("Donja Gruža", "Gruža", 43.900, 20.650, "Kragujevac", "knezina"),
    ("Batočina", "Batočina", 44.155, 21.080, "Kragujevac", "village"),
    # Jagodina nahija: Levač, and Ivankovac on the Morava, where the Sultan's army was beaten in August 1805.
    ("Levač", "Rekovac", 43.862, 21.093, "Jagodina", "knezina"),
    ("Ivankovac", "Ivankovac", 43.930, 21.380, "Jagodina", "village"),
    # The Jasenica knežina, which rose with Orašac: Karađorđe's Topola, and Vrbica, where Kučuk-Alija struck in March 1804.
    ("Topola", "Topola", 44.255, 20.682, "Orašac", "village"),
    ("Vrbica", "Vrbica", 44.320, 20.550, "Orašac", "village"),
    ("Natalinci", "Natalinci", 44.240, 20.830, "Orašac", "village"),
    ("Darosava", "Darosava", 44.360, 20.450, "Orašac", "village"),
    # Rudnik nahija: Crna Gora under Takovo, Kačer, and Milan Obrenović's Brusnica.
    ("Crna Gora", "Takovo", 44.050, 20.370, "Rudnik", "knezina"),
    ("Kačer", "Belanovica", 44.250, 20.400, "Rudnik", "knezina"),
    ("Brusnica", "Brusnica", 44.030, 20.450, "Rudnik", "village"),
    # Ljubić on the Zapadna Morava by Čačak, down the valley south of Brusnica.
    ("Ljubić", "Ljubić", 43.917, 20.392, "Rudnik", "village"),
    # Valjevo nahija: its knežine, and Brankovina, home of the Nenadovići.
    ("Valjevska Tamnava", "Ub", 44.456, 20.075, "Valjevo", "knezina"),
    ("Kolubara", "Mionica", 44.250, 20.080, "Valjevo", "knezina"),
    ("Ljig", "Ljig", 44.225, 20.237, "Valjevo", "knezina"),
    ("Brankovina", "Brankovina", 44.360, 19.880, "Valjevo", "village"),
    # Podgorina under Medvednik, the knežina of Ilija Birčanin, killed at Valjevo in the slaughter of the knezes.
    ("Podgorina", "Osečina", 44.373, 19.601, "Valjevo", "knezina"),
    # Kosjerić in the Skrapež valley between Maljen and Povlen, south of Valjevo over the mountains.
    ("Kosjerić", "Kosjerić", 43.997, 19.907, "Valjevo", "village"),
    # Sokol nahija: Rađevina round Krupanj and Azbukovica round Ljubovija, both on the Drina, at villages back from the
    # river, as Krupanj and Ljubovija lie on the map's edge.
    ("Rađevina", "Bela Crkva", 44.396, 19.479, "Sokol", "knezina"),
    ("Azbukovica", "Leović", 44.196, 19.492, "Sokol", "knezina"),
    # Bajina Bašta on the Drina below Tara, where the valley opens south of the gorge.
    ("Bajina Bašta", "Bajina Bašta", 43.971, 19.566, "Sokol", "village"),
    # Šabac nahija: Mačva, Pocerina under Cer, and Posavina, and the fields of Mišar (1806) and Svileuva (1804).
    ("Mačva", "Bogatić", 44.835, 19.480, "Šabac", "knezina"),
    ("Pocerina", "Dvorište", 44.603, 19.579, "Šabac", "knezina"),
    ("Posavina", "Provo", 44.670, 19.910, "Šabac", "knezina"),
    ("Mišar", "Mišar", 44.735, 19.755, "Šabac", "village"),
    ("Svileuva", "Svileuva", 44.521, 19.828, "Šabac", "village"),
]


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
    return get("https://overpass-api.de/api/interpreter", data=query)


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
                    elev += [r["elevation"] for r in data["results"]]
                    break
            except Exception as e:  # noqa: BLE001 - retry any network hiccup
                print("retrying", k, e)
            time.sleep(3)
        else:
            raise SystemExit(f"elevation download failed at {k}")
        time.sleep(1.1)
    return {"w": DEM_W, "h": DEM_H, "elev": elev}


bbox = f"({LAT0},{LON0},{LAT1},{LON1})"
places = cached("places.json", lambda: overpass(f'[out:json][timeout:80];node["place"~"^(village|town|city|hamlet)$"]{bbox};out;'))


def fetch_rivers():
    """Named rivers, a quarter of the map at a time: the whole box at once is more than the server will answer. A way
    that crosses into two quarters comes back from both and is kept once."""
    ways = {}
    mid_lat, mid_lon = (LAT0 + LAT1) / 2, (LON0 + LON1) / 2
    for la0, la1 in ((LAT0, mid_lat), (mid_lat, LAT1)):
        for lo0, lo1 in ((LON0, mid_lon), (mid_lon, LON1)):
            part = overpass(f'[out:json][timeout:170];way["waterway"="river"]["name"]({la0},{lo0},{la1},{lo1});out geom;')
            for way in part["elements"]:
                ways[way["id"]] = way
    return {"elements": list(ways.values())}


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
    chains = [list(c) for c in chains]
    merged = True
    while merged:
        merged = False
        for a in range(len(chains)):
            for b in range(len(chains)):
                if a == b:
                    continue
                A, B = chains[a], chains[b]
                same = lambda p, q: abs(p[0] - q[0]) < 1e-7 and abs(p[1] - q[1]) < 1e-7
                if same(A[-1], B[0]):
                    chains[a] = A + B[1:]
                elif same(A[-1], B[-1]):
                    chains[a] = A + B[::-1][1:]
                elif same(A[0], B[-1]):
                    chains[a] = B + A[1:]
                elif same(A[0], B[0]):
                    chains[a] = B[::-1] + A[1:]
                else:
                    continue
                del chains[b]
                merged = True
                break
            if merged:
                break
    return chains


by_name = {}
for way in rivers_raw["elements"]:
    name = way["tags"].get("name:sr-Latn") or way["tags"].get("name")
    if not name or "geometry" not in way:
        continue
    by_name.setdefault(name, []).append([(g["lat"], g["lon"]) for g in way["geometry"]])

rivers = []  # (name, major, [(x, y)])
for name, ways in sorted(by_name.items()):
    for chain in join(ways):
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
    tags = el["tags"]
    name = tags.get("name:sr-Latn") or tags.get("name")
    if name:
        survey.append({"name": name, "place": tags.get("place"), "lat": el["lat"], "lon": el["lon"]})

# Each place stands where the survey puts the place of its name nearest the given point, within 15 km; one that is not
# found stops the build with the villages around the point to choose from instead.
chosen = []
for name, osm, lat, lon, parent, kind in PLACES:
    near = sorted((km((s["lat"], s["lon"]), (lat, lon)), s["name"], s) for s in survey)
    found = [(d, s) for d, n, s in near if n == osm and d <= 15]
    if not found:
        around = ", ".join(f"{n} ({s['place']}, {d:.1f} km)" for d, n, s in near[:12])
        raise SystemExit(f"{name}: no {osm!r} within 15 km of {lat}, {lon}. Near there: {around}")
    s = found[0][1]
    x, y = to_map(s["lat"], s["lon"])
    if not (0.7 * SCALE <= x <= WIDTH - 0.7 * SCALE and 0.7 * SCALE <= y <= HEIGHT - 0.7 * SCALE):
        raise SystemExit(f"{name} ({osm}) lies too near the edge of the map, at {x:.1f}, {y:.1f}")
    chosen.append({"name": name, "kind": kind, "parent": parent, "lat": s["lat"], "lon": s["lon"], "hex": hex_at(x, y)})
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

# A town on a border river stands on its near bank: Belgrade, Šabac and Smederevo look over the water at Austria, and a
# settlement in the river's own hex would be a way across it. It moves to a dry neighbour on the near, southern side,
# the one that keeps furthest from the other places.
for c in chosen:
    if c["hex"] in border_hexes:
        others = [o["hex"] for o in chosen if o is not c]
        dry = [n for n in neighbours(*c["hex"]) if n not in river_hexes and n[1] >= c["hex"][1] and n not in others]
        assert dry, c["name"]
        c["hex"] = max(dry, key=lambda n: (min(3, min(steps(n, o) for o in others)), n[1], -abs(n[0] - c["hex"][0])))
        print("moved to the bank:", c["name"], c["hex"])
# Places stand at least two hexes apart, so an army at one is never taken for being at its neighbour.
for i, a in enumerate(chosen):
    for b in chosen[i + 1:]:
        if steps(a["hex"], b["hex"]) < 2:
            raise SystemExit(f"{a['name']} and {b['name']} are only {steps(a['hex'], b['hex'])} hex apart")
settlement_hexes = {c["hex"]: c for c in chosen}
settlement_pts = [center(*c["hex"]) for c in chosen]

terrain = {}
info = {}
for r in range(ROWS):
    for c in range(COLS):
        x, y = center(c, r)
        samples = [elevation(x, y)] + [elevation(x + 0.42 * SCALE * math.cos(a), y + 0.42 * SCALE * math.sin(a)) for a in [k * math.pi / 3 + math.pi / 6 for k in range(6)]]
        e = samples[0]
        relief = max(samples) - min(samples)
        d_place = min(math.hypot(x - px, y - py) for px, py in settlement_pts)
        d_major = distance_to(major, x, y)
        wild = 0.6 * noise(x, y, 4.5 * SCALE, 11) + 0.4 * noise(x, y, 1.7 * SCALE, 23)
        score = (wild + 0.25 * clamp((e - 160) / 380) + 0.2 * clamp(relief / 150)
                 - 0.95 * clamp(1 - d_place / (2.5 * SCALE)) - 0.3 * clamp(1 - d_major / (1.6 * SCALE)))
        info[(c, r)] = (e, relief, d_place, score)

# A little over half the open land under oak: the score above which a hex is forest, set as the 42nd percentile when the
# map had its first 44 places and held there since, so a place added later clears its own ground without moving the
# forest line, and with it the woods, across the rest of the map. Without the pin the four places of the Drina corner
# turned 114 hexes of meadow elsewhere to forest.
FOREST_LINE = 0.42901713633778404

for (c, r), (e, relief, d_place, score) in info.items():
    x, y = center(c, r)
    pick = noise(x, y, 1.3 * SCALE, 37)
    hilly = e >= 390 or relief >= 105
    if (c, r) in river_hexes:
        t = "~"
    elif (e >= 660 or (e >= 560 and relief >= 150)) and (c, r) not in settlement_hexes:
        t = "M"
    elif (c, r) in settlement_hexes:
        t = "o" if pick < 0.45 else "w"
    elif d_place <= 1.05 * SCALE:
        # Next to the houses: plum orchards on the slopes, a few fields, the rest pasture.
        t = "o" if pick < 0.38 and e > 150 else "w" if pick < 0.66 else "h" if hilly else "."
    elif score > FOREST_LINE:
        t = "F" if hilly else "f"
    elif d_place <= 2.1 * SCALE:
        t = "w" if pick > 0.78 and relief < 80 else "o" if pick < 0.12 else "h" if hilly else "."
    else:
        t = "h" if hilly else "."
    # Creeks keep a strip of wet meadow through open land; in the forest they stay under the trees.
    if (c, r) in stream_hexes and t in ".who":
        t = "s"
    terrain[(c, r)] = t

# Passes: mountain hexes a road crossed, left as wooded hills so the land beyond is not cut off. Sokol and Azbukovica lie
# in a pocket of the Drina valley that the mountains close on every side but the river's; the way over Boranja from
# Rađevina comes down to Sokol at (3, 32). Without it guns, carts and Ottoman columns could not reach them at all. The
# way from Valjevo to Kosjerić goes over the saddle between Maljen and Povlen (16, 39–42), and the way up the Zapadna
# Morava runs under the cliffs on its north bank through the gorge of Ovčar and Kablar (24, 51), where the mountains
# otherwise come down to the water and a track could only follow the river from ford to ford. The way from Azbukovica
# down the Drina to Bajina Bašta runs along the river's foot under Tara (4, 38–39; 6, 42; 8, 42–43), and from Bajina
# Bašta over to Kosjerić by Kostojevići (12, 46).
PASSES = {(3, 32): "F", (16, 39): "F", (16, 40): "F", (16, 41): "F", (16, 42): "F", (24, 51): "F",
          (4, 38): "F", (4, 39): "F", (6, 42): "F", (8, 42): "F", (8, 43): "F", (12, 46): "F"}
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
    e, relief = info[h][0], info[h][1]
    return e >= 390 or relief >= 105


def trade_of(h):
    """What a village lives off: the land within three hexes of it (about 2.5 km), its fields, orchards and meadows and
    the edge of the woods. Each kind of ground counts toward its trade and the most wins; the woods count more, since
    they begin only where the village's clearing ends. Mountains close by make it a mining village."""
    if sum(terrain[x] == "M" for x in within(h, 2)) >= 2:
        return "iron"
    near = {}
    for x in within(h, 3):
        near[terrain[x]] = near.get(terrain[x], 0) + 1
    n = lambda chars: sum(near.get(ch, 0) for ch in chars)
    scores = [("grain", n("w")), ("plums", n("o") * 1.2), ("livestock", n(".hs") * 0.9), ("wood", n("fF") * 1.6)]
    return max(scores, key=lambda s: s[1])[0]  # the first of equal scores wins


# Villages that live otherwise than their land alone suggests, by name: Bajina Bašta, under the mountains, lives off the
# forest and the timber floated down the Drina rather than the mines.
TRADE = {"Bajina Bašta": "wood"}

villages = [c for c in chosen if c.get("parent")]
for c in villages:
    c["trade"] = TRADE.get(c["name"]) or trade_of(c["hex"])

# Each village's clearing then shows its trade. A wood village has the woods reach in to its houses from the side of the
# nearest forest; a herding village turns its fields and orchards to meadow, but for two by the houses; a plum or grain
# village has at least three orchards or fields next to it. Only ground nearer the village than any other place changes,
# and never a river, creek or crossing.
forest = [h for h in terrain if terrain[h] in "fF"]
for c in villages:
    v, trade = c["hex"], c["trade"]
    others = [s for s in settlement_hexes if s != v]
    def own(h):
        return h not in settlement_hexes and terrain[h] in ".who" and all(steps(h, v) < steps(h, s) for s in others)
    ring1 = [h for h in within(v, 1) if h != v and own(h)]
    ring2 = [h for h in within(v, 2) if steps(h, v) == 2 and own(h)]
    if trade == "wood":
        woods = min(forest, key=lambda h: (steps(h, v), h[1], h[0]))
        d = steps(v, woods)
        for h in within(v, d):
            if h != v and steps(v, h) + steps(h, woods) == d and terrain[h] in ".who" and h not in settlement_hexes \
                    and (steps(v, h) > 2 or own(h)):
                terrain[h] = "F" if hilly(h) else "f"
    elif trade == "livestock":
        keep = [h for h in ring1 if terrain[h] in "wo"][:2]
        for h in ring1 + ring2:
            if terrain[h] in "wo" and h not in keep:
                terrain[h] = "h" if hilly(h) else "."
    elif trade in ("plums", "grain"):
        ground = "o" if trade == "plums" else "w"
        have = sum(terrain[h] == ground for h in within(v, 1) if h != v)
        for h in ring1:
            if have >= 3:
                break
            if terrain[h] != ground:
                terrain[h] = ground
                have += 1
for c in villages:
    if c["name"] not in TRADE and trade_of(c["hex"]) != c["trade"]:
        print("note:", c["name"], "now reads as", trade_of(c["hex"]), "but lives off", c["trade"])

rows = ["".join(terrain[(c, r)] for c in range(COLS)) for r in range(ROWS)]

# ---------------------------------------------------------------- output

for r, row in enumerate(rows):
    print(("  " if r & 1 else "") + " ".join(row))
tally = {}
for row in rows:
    for ch in row:
        tally[ch] = tally.get(ch, 0) + 1
print(tally, len(chosen), "settlements", counts)


def q(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


lines = [
    "//",
    "//  DistrictData.swift",
    "//  Broba pod sljivom",
    "//",
    "//  Generated by Tools/district/make_district.py; edit that script, not this file.",
    "//  Heights: SRTM 90 m via OpenTopoData. Rivers and villages: © OpenStreetMap contributors (ODbL).",
    "//",
    "",
    "import Foundation",
    "",
    "nonisolated enum DistrictData {",
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
    "    /// The town, the seats and the places under them: name, hex column and row, the seat a place belongs to, what it",
    "    /// lives off (a seat's trade is set in the game), and what it is: town, nahija, knezina or village.",
    "    static let places: [(name: String, col: Int, row: Int, parent: String?, trade: String?, kind: String)] = [",
]
for c in chosen:
    parent = f'"{c["parent"]}"' if c.get("parent") else "nil"
    trade = f'"{c["trade"]}"' if c.get("trade") else "nil"
    lines.append(f'        ("{c["name"]}", {c["hex"][0]}, {c["hex"][1]}, {parent}, {trade}, "{c["kind"]}"),')
lines += ["    ]", "}", ""]
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("wrote", os.path.normpath(OUT))

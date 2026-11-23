#!/usr/bin/env python3
"""Builds Campaign/OrasacData.swift: the hex map of the Orašac district as it might have looked in 1804, the map of
the short campaign. The long campaign's map of the Belgrade pashaluk is made by make_district.py.

Heights come from SRTM (90 m, through the OpenTopoData API); rivers and villages from OpenStreetMap
(through the Overpass API). Forest, fields, orchards and meadows are not in any survey of 1804, so they are
modelled: Šumadija was still mostly oak forest, with fields and plum orchards in clearings around the villages
and wet meadows along the rivers. What each village lives off is read from the land around it, and its clearing is
then shaped to show it.

Run from the repository root:

    python3 Tools/district/make_orasac.py

Downloads are cached in Tools/district/cache-orasac, so later runs only redo the classification.
"""
import json
import math
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache-orasac")
OUT = os.path.join(HERE, "..", "..", "Broba pod sljivom", "Campaign", "OrasacData.swift")
AGENT = {"User-Agent": "BorbaPodSljivom-mapbuild/0.1"}

# The map: longitude 20.40–21.15 E, latitude 44.38 N down to about 43.98 N.
LON0, LON1, LAT0, LAT1 = 20.40, 21.15, 43.98, 44.38
# Hexes per 1.7 km: the grid was 34 × 29 hexes of 1.7 km; at 2 it is 68 × 58 hexes of about 0.85 km. Distances below
# that are given in map units are multiplied by it, so the land keeps its shape on the ground.
SCALE = 2
COLS, ROWS = 34 * SCALE, 29 * SCALE
ROW_STEP = math.sqrt(3) / 2      # pointy-top hexes, one unit wide
RADIUS = 1 / math.sqrt(3)        # centre to corner
WIDTH = COLS + 0.5
HEIGHT = (ROWS - 1) * ROW_STEP + 2 * RADIUS
KM_PER_LON = 111.32 * math.cos(math.radians((LAT0 + LAT1) / 2))
KM_PER_UNIT = (LON1 - LON0) * KM_PER_LON / WIDTH
UNITS_PER_LAT = 111.13 / KM_PER_UNIT
DEM_W, DEM_H = 96, 72
# Forest hexes cleared by hand: along the river north of Sepci and by the Austria gate, for the tracks there; and where
# the finer grid closed the old ways between Vrbica and Vukosavci, Bukovik and Darosava, Bosuta and Garaši, and
# Đurđevo and Popović.
CLEARED = [(42, 10), (42, 9), (43, 8), (44, 8), (44, 7), (49, 2), (49, 1), (52, 1), (51, 1), (12, 14), (11, 15), (7, 7), (4, 17),
           (45, 21), (46, 21)]

# Rivers an army cannot wade, with the stretch where each becomes one; upstream they are creeks.
MAJOR_RIVERS = {
    "Velika Morava": lambda x, y: True,
    "Jasenica": lambda x, y: x >= 12 * SCALE,     # below Šatornja
    "Lepenica": lambda x, y: x >= 22.5 * SCALE,   # from Kragujevac down to the Morava
}
SEATS = {  # name in OpenStreetMap -> villages it gathers
    "Kragujevac": 4, "Orašac": 3, "Vrbica": 4, "Topola": 6, "Stragari": 6, "Rača": 6, "Natalinci": 6, "Velika Plana": 6,
    "Živkovci": 3,
}
# Places that did not exist in 1804, or were Ottoman towns rather than villages, or duplicate another name.
SKIP = {"Aranđelovac", "Gornji Milanovac", "Smederevska Palanka", "Lapovo", "Topola (selo)", "Lapovo (selo)"}
# Villages given to a seat by hand rather than to the nearest: the far west hangs together under Živkovci.
PARENT = {"Darosava": "Živkovci", "Garaši": "Živkovci", "Bosuta": "Živkovci"}
# Villages nudged from where the survey puts them, in map units (x across, y down): Bosuta a little up and to the left,
# nearer the rest of its knežina.
NUDGE = {"Bosuta": (-1.4, -1.6)}


def to_map(lat, lon):
    return ((lon - LON0) / (LON1 - LON0) * WIDTH, (LAT1 - lat) * UNITS_PER_LAT)


def to_geo(x, y):
    return (LAT1 - y / UNITS_PER_LAT, LON0 + x / WIDTH * (LON1 - LON0))


# ---------------------------------------------------------------- downloads

def cached(name, fetch):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w") as f:
            json.dump(fetch(), f)
    with open(path) as f:
        return json.load(f)


def overpass(query):
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=data, headers=AGENT)
    return json.load(urllib.request.urlopen(req, timeout=180))


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
                data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=60))
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
rivers_raw = cached("rivers.json", lambda: overpass(f'[out:json][timeout:110];way["waterway"="river"]{bbox};out geom;'))
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
                test = MAJOR_RIVERS.get(name, lambda x, y: False)
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


candidates = []
for el in places["elements"]:
    tags = el["tags"]
    name = tags.get("name:sr-Latn") or tags.get("name")
    if not name or name in SKIP:
        continue
    x, y = to_map(el["lat"], el["lon"])
    dx, dy = NUDGE.get(name, (0, 0))
    x, y = x + dx, y + dy
    if not (0.7 * SCALE <= x <= WIDTH - 0.7 * SCALE and 0.7 * SCALE <= y <= HEIGHT - 0.7 * SCALE):
        continue
    lat, lon = to_geo(x, y)
    candidates.append({"name": name, "place": tags.get("place"), "lat": lat, "lon": lon, "hex": hex_at(x, y)})

seats = {}
for c in candidates:
    if c["name"] in SEATS and (c["name"] not in seats or c["place"] in ("city", "town")):
        seats[c["name"]] = c
missing = set(SEATS) - set(seats)
assert not missing, missing

chosen = list(seats.values())
taken_hexes = {c["hex"] for c in chosen}
pool = []
for c in candidates:
    if c["place"] != "village" or c["name"] in SEATS:
        continue
    parent, d = min(((s, km((c["lat"], c["lon"]), (seats[s]["lat"], seats[s]["lon"]))) for s in SEATS), key=lambda t: t[1])
    if c["name"] in PARENT:
        parent = PARENT[c["name"]]
        d = km((c["lat"], c["lon"]), (seats[parent]["lat"], seats[parent]["lon"]))
    if d <= 15:
        pool.append((d, parent, c))
counts = {s: 0 for s in SEATS}
# Villages given by hand come first, and keep their place however close they stand to another.
for d, parent, c in sorted(pool, key=lambda t: (t[2]["name"] not in PARENT, t[0])):
    if counts[parent] >= SEATS[parent] or c["hex"] in taken_hexes:
        continue
    if c["name"] not in PARENT and any(km((c["lat"], c["lon"]), (o["lat"], o["lon"])) < 2.9 for o in chosen):
        continue
    c["parent"] = parent
    chosen.append(c)
    taken_hexes.add(c["hex"])
    counts[parent] += 1
# A seat that came up short takes villages left over near it, even ones a little closer to a neighbour.
for name in SEATS:
    seat = seats[name]
    spare = sorted(((km((c["lat"], c["lon"]), (seat["lat"], seat["lon"])), c["name"], c) for _, _, c in pool if "parent" not in c), key=lambda t: t[:2])
    for d, _, c in spare:
        if counts[name] >= SEATS[name] or d > 11:
            break
        if c["hex"] in taken_hexes or any(km((c["lat"], c["lon"]), (o["lat"], o["lon"])) < 2.9 for o in chosen):
            continue
        c["parent"] = name
        chosen.append(c)
        taken_hexes.add(c["hex"])
        counts[name] += 1
settlement_hexes = {c["hex"]: c for c in chosen}
settlement_pts = [center(*c["hex"]) for c in chosen]

# ---------------------------------------------------------------- terrain

major = [pts for name, is_major, pts in rivers if is_major]
minor = [pts for name, is_major, pts in rivers if not is_major]
river_hexes, stream_hexes = set(), set()
river_paths = [raster(p) for p in major]
for path in river_paths:
    river_hexes.update(path)
for p in minor:
    stream_hexes.update(raster(p))

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

land = [k for k in info if k not in river_hexes and k not in settlement_hexes]
scores = sorted(info[k][3] for k in land)
forest_line = scores[int(len(scores) * 0.42)]  # a little over half the open land under oak

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
    elif score > forest_line:
        t = "F" if hilly else "f"
    elif d_place <= 2.1 * SCALE:
        t = "w" if pick > 0.78 and relief < 80 else "o" if pick < 0.12 else "h" if hilly else "."
    else:
        t = "h" if hilly else "."
    # Creeks keep a strip of wet meadow through open land; in the forest they stay under the trees.
    if (c, r) in stream_hexes and t in ".who":
        t = "s"
    terrain[(c, r)] = t

# Crossings: a bridge or ford every few hexes along the big rivers, and wherever a settlement stands by the water.
seat_hexes = {seats[s]["hex"] for s in SEATS}
for path in river_paths:
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

# Forest cleared by hand (see CLEARED): wooded hills become open hills, woods become meadow.
for h in CLEARED:
    terrain[h] = "h" if terrain[h] == "F" else "."

# ---------------------------------------------------------------- what the villages live off


def steps(a, b):
    qa, qb = a[0] - (a[1] - (a[1] & 1)) // 2, b[0] - (b[1] - (b[1] & 1)) // 2
    dq, dr = qa - qb, a[1] - b[1]
    return max(abs(dq), abs(dr), abs(dq + dr))


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


# Villages that live otherwise than their land alone suggests: Natalinci keeps some herding and orchards beside its grain.
TRADE = {"Junkovac": "livestock", "Kloka": "plums"}

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
    "//  OrasacData.swift",
    "//  Broba pod sljivom",
    "//",
    "//  Generated by Tools/district/make_orasac.py; edit that script, not this file. The map of the short campaign:",
    "//  the Orašac district round Topola, as it was before the campaign grew to the Belgrade pashaluk.",
    "//  Heights: SRTM 90 m via OpenTopoData. Rivers and villages: © OpenStreetMap contributors (ODbL).",
    "//",
    "",
    "import Foundation",
    "",
    "nonisolated enum OrasacData {",
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
    "    /// The town, the knežine and their villages: name, hex column and row, the seat a village belongs to, and what a",
    "    /// village lives off (a seat's trade is set in the game).",
    "    static let places: [(name: String, col: Int, row: Int, parent: String?, trade: String?)] = [",
]
for c in chosen:
    parent = f'"{c["parent"]}"' if c.get("parent") else "nil"
    trade = f'"{c["trade"]}"' if c.get("trade") else "nil"
    lines.append(f'        ("{c["name"]}", {c["hex"][0]}, {c["hex"][1]}, {parent}, {trade}),')
lines += ["    ]", "}", ""]
with open(OUT, "w") as f:
    f.write("\n".join(lines))
print("wrote", os.path.normpath(OUT))

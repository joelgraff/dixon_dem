"""Match the downtown National Register inventory to footprints.

Reads the nomination text extracted from the PDF, keeps rows that name a
street address and a style we can build, geocodes each address, and writes an
override only when one footprint is clearly the nearest. Existing overrides
are left alone. Pass --apply to write; otherwise it only prints the plan.
"""
import json
import math
import os
import re
import time
import urllib.parse
import urllib.request

from pyproj import Transformer
from shapely.geometry import Point, Polygon

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TEXT = os.path.join(ROOT, "data", "raw", "references", "dixon_nrhp.txt")
PDF = os.path.join(ROOT, "data", "raw", "references", "dixon_downtown_historic_district_12000059.pdf")
CACHE = os.path.join(ROOT, "data", "raw", "references", "nrhp_geocode.json")
OVERRIDES = os.path.join(ROOT, "game", "data", "building_overrides.json")
BUILDINGS = os.path.join(ROOT, "game", "data", "buildings.json")
ORIGIN_E = 292300.0
ORIGIN_N = 4634000.0
_T = Transformer.from_crs("EPSG:4326", "EPSG:26916", always_xy=True)

STREET = re.compile(
    r"(\d{1,4}(?:-\d{1,4})?)\s+((?:East|West|North|South)\s+.+?(?:Street|Avenue))",
    re.I,
)


def _style_template(style):
    s = style.lower()
    s = s.replace("ajnerican", "american").replace("chioago", "chicago")
    if "italianate" in s:
        return {"form": "party_wall_commercial", "dressing": "italianate", "material": "brick",
                "storeys": 2, "roof": "flat_parapet", "roof_axis": "side", "porch": "none"}
    if "commercial style" in s or "chicago style" in s:
        return {"form": "party_wall_commercial", "dressing": "commercial_1900", "material": "brick",
                "storeys": 2, "roof": "flat_parapet", "roof_axis": "side", "porch": "none"}
    if "bungalow" in s or "craftsman" in s:
        return {"form": "bungalow", "dressing": "craftsman", "material": "clapboard",
                "storeys": 1.5, "roof": "gable", "roof_axis": "side", "porch": "gable_full"}
    if "queen anne" in s:
        return {"form": "gabled_ell", "dressing": "folk_victorian", "material": "clapboard",
                "storeys": 2, "roof": "gable", "roof_axis": "side", "porch": "ell_corner"}
    if "romanesque" in s or "classical" in s or "beaux" in s:
        return {"form": "civic_block", "dressing": "plain", "material": "limestone",
                "storeys": 2, "roof": "flat_parapet", "roof_axis": "side", "porch": "stoop"}
    if "gothic" in s:
        return {"form": "church_nave", "dressing": "plain", "material": "brick",
                "storeys": 1, "roof": "gable", "roof_axis": "front", "porch": "stoop", "tower": True}
    if "prairie" in s or "foursquare" in s:
        return {"form": "foursquare", "dressing": "plain", "material": "clapboard",
                "storeys": 2, "roof": "pyramidal", "roof_axis": "side", "porch": "shed_full"}
    return None


def parse_inventory(text):
    start = text.find("No.        Address")
    if start < 0:
        start = text.find("Inventory")
    rows = []
    for line in text[start:].splitlines():
        if not re.search(r"\b(Yes|No)\s*$", line):
            continue
        parts = [p.strip() for p in re.split(r"\s{2,}", line.strip()) if p.strip()]
        if len(parts) < 3 or parts[-1] not in ("Yes", "No"):
            continue
        address = ""
        number = ""
        for part in parts:
            m = STREET.search(part)
            if m:
                number, address = m.group(1), m.group(2).strip(" .")
                break
        if not address:
            continue
        style = ""
        for part in parts:
            if ":" in part or part.lower().startswith("other") or "style" in part.lower() or "victorian" in part.lower():
                style = part
        if not style:
            continue
        template = _style_template(style)
        if template is None or parts[-1] != "Yes":
            continue
        rows.append({"number": number, "street": address, "style": style, "template": template})
    return rows


def _load_cache():
    if os.path.exists(CACHE):
        with open(CACHE) as handle:
            return json.load(handle)
    return {}


_TYPE = {"street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "lane": "ln"}
_NUM = {"first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th"}


def _street_key(text):
    words = re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()
    words = [_NUM.get(w, w) for w in words]
    words = [_TYPE.get(w, w) for w in words]
    dirs = {"east": "e", "west": "w", "north": "n", "south": "s"}
    words = [dirs.get(w, w) for w in words]
    key = " ".join(words)
    # East of Galena Avenue, River Street is signed River Road.
    if "e river st" in key:
        key = key.replace("e river st", "e river rd")
    return key


def geocode(number, street, cache):
    query = f"census:{number} {street}"
    cached = cache.get(query)
    # Re-check old "street mismatch" entries. The River Street / River Road
    # rule was added after those were cached.
    if cached is not None and not str(cached.get("error", "")).startswith("street mismatch"):
        return cached
    url = "https://geocoding.geo.census.gov/geocoder/locations/address?" + urllib.parse.urlencode({
        "street": f"{number} {street}", "city": "Dixon", "state": "IL",
        "benchmark": "Public_AR_Current", "format": "json",
    })
    req = urllib.request.Request(url, headers={"User-Agent": "dixon-dem-local/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        cache[query] = {"error": str(exc)}
        return cache[query]
    matches = data.get("result", {}).get("addressMatches") or []
    if not matches:
        cache[query] = {"error": "no result"}
    else:
        matched = matches[0].get("matchedAddress", "")
        # "201 E RIVER RD" is not "East River Street". Reject a different road type.
        if _street_key(street) not in _street_key(matched):
            cache[query] = {"error": f"street mismatch: {matched}"}
        else:
            cache[query] = {
                "lat": float(matches[0]["coordinates"]["y"]),
                "lon": float(matches[0]["coordinates"]["x"]),
                "matched": matched,
            }
    time.sleep(0.25)
    return cache[query]


def to_local(lon, lat):
    east, north = _T.transform(lon, lat)
    return east - ORIGIN_E, -(north - ORIGIN_N)


def footprints():
    with open(BUILDINGS) as handle:
        buildings = json.load(handle)["buildings"]
    out = []
    for record in buildings:
        if record.get("landmark_id"):
            continue
        pts = [(p["x"], p["z"]) for p in record.get("footprint") or []]
        if len(pts) < 3:
            continue
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        out.append((record["id"], poly))
    return out


def nearest(x, z, places):
    """Distance to the footprint itself. A downtown point sits in the street,
    so the wall can be close while the centroid is not."""
    best = None
    second = 1e9
    point = Point(x, z)
    for bid, poly in places:
        d = poly.distance(point)
        if best is None or d < best[0]:
            second = best[0] if best else second
            best = (d, bid)
        elif d < second:
            second = d
    return best, second


def main():
    import sys
    apply = "--apply" in sys.argv
    if not os.path.exists(TEXT):
        os.system(f'pdftotext -layout "{PDF}" "{TEXT}"')
    text = open(TEXT, encoding="utf-8", errors="replace").read()
    rows = parse_inventory(text)
    print(f"usable inventory rows: {len(rows)}")
    if not apply:
        from collections import Counter
        print(Counter(r["template"]["form"] + "/" + r["template"]["dressing"] for r in rows))
        return
    cache = _load_cache()
    places = footprints()
    overrides = {}
    if os.path.exists(OVERRIDES):
        with open(OVERRIDES) as handle:
            overrides = json.load(handle).get("buildings", {})
    placed = 0
    skipped = 0
    for row in rows:
        hit = geocode(row["number"], row["street"], cache)
        if "lat" not in hit:
            skipped += 1
            continue
        x, z = to_local(hit["lon"], hit["lat"])
        best, second = nearest(x, z, places)
        if best is None or best[0] > 18.0 or second < best[0] + 4.0:
            skipped += 1
            continue
        bid = str(best[1])
        if bid in overrides:
            skipped += 1
            continue
        overrides[bid] = dict(row["template"])
        overrides[bid]["note"] = f"{row['number']} {row['street']}"
        placed += 1
        print(f"  {bid}  {best[0]:.0f}m  {row['number']} {row['street']}  -> {row['template']['form']}")
    review = os.path.join(ROOT, "game", "data", "nrhp_unmatched.json")
    if os.path.exists(review):
        with open(review) as handle:
            for item in json.load(handle):
                bid = str(item.get("building_id") or "").strip()
                if not bid or bid in overrides:
                    continue
                template = _style_template(item.get("style", ""))
                if template is None:
                    continue
                overrides[bid] = template
                overrides[bid]["note"] = item.get("corrected_address") or item.get("address")
                placed += 1
                print(f"  {bid}  hand  {overrides[bid]['note']}")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as handle:
        json.dump(cache, handle)
    with open(OVERRIDES, "w") as handle:
        json.dump({"buildings": overrides}, handle, indent=1)
    print(f"placed {placed}, skipped {skipped}")


if __name__ == "__main__":
    main()

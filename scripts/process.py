"""Consolidate paginated Strava data into a single payload for the viz."""
from __future__ import annotations
import glob, json, math, statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted((ROOT / "data" / "pages").glob("page-*.json"))
OUT = ROOT / "data" / "rides.json"

CYCLING = {"Ride", "VirtualRide", "EBikeRide", "MountainBikeRide", "GravelRide", "Velomobile"}


def _region(lat: float, lng: float) -> str:
    if 55.4 < lat < 56.1 and 12.0 < lng < 12.9:
        return "Copenhagen"
    if 39.4 < lat < 40.0 and 2.2 < lng < 3.5:
        return "Mallorca"
    if 47.0 < lat < 48.0 and -123.3 < lng < -121.5:
        return "Seattle"
    if 37.5 < lat < 38.0 and -122.6 < lng < -121.8:
        return "Bay Area"
    if 50.8 < lat < 51.6 and -0.6 < lng < 0.6:
        return "London"
    if 40.5 < lat < 41.0 and -74.2 < lng < -73.5:
        return "New York"
    if 38.7 < lat < 39.1 and -77.2 < lng < -76.8:
        return "Washington DC"
    return "Other"


def decode_polyline(s: str) -> list[tuple[float, float]]:
    """Google-encoded polyline → [(lat, lng), ...]."""
    if not s:
        return []
    coords, i, lat, lng = [], 0, 0, 0
    while i < len(s):
        for _ in range(2):
            shift, result = 0, 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if _ == 0:
                lat += delta
            else:
                lng += delta
        coords.append((lat / 1e5, lng / 1e5))
    return coords


def simplify(points: list[tuple[float, float]], every: int) -> list[tuple[float, float]]:
    if every <= 1 or len(points) <= 2:
        return points
    out = points[::every]
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def main() -> None:
    rides = []
    for p in PAGES:
        d = json.loads(p.read_text())
        for a in d["activities"]:
            if a["sport_type"] not in CYCLING:
                continue
            poly = decode_polyline(a.get("reduced_polyline", ""))
            poly = simplify(poly, every=2)
            s = a["summary"]
            tags = a.get("activity_tags") or []
            is_commute = bool(a.get("is_commute"))
            is_trainer = bool(a.get("is_trainer"))
            has_workout = "Workout" in tags
            has_race = "Race" in tags
            rides.append({
                "id": a["id"],
                "name": a.get("name", ""),
                "sport": a["sport_type"],
                "start": a["start_local"],
                "year": int(a["start_local"][:4]),
                "distance_km": round(s["distance"] / 1000, 3),
                "moving_h": round(s["moving_time"] / 3600, 4),
                "elev_m": round(s.get("elevation_gain") or 0, 1),
                "avg_kmh": round((s.get("avg_speed") or 0) * 3.6, 2),
                "max_kmh": round((s.get("max_speed") or 0) * 3.6, 2),
                "calories": s.get("total_calories"),
                "kudos": s.get("kudos_count", 0),
                "commute": is_commute,
                "trainer": is_trainer,
                "workout": has_workout,
                "race": has_race,
                "tags": tags,
                "path": [[round(lat, 5), round(lng, 5)] for lat, lng in poly],
            })

    rides.sort(key=lambda r: r["start"])
    by_year = defaultdict(list)
    for r in rides:
        by_year[r["year"]].append(r)

    yearly = []
    for y, items in sorted(by_year.items()):
        dist = sum(r["distance_km"] for r in items)
        time_h = sum(r["moving_h"] for r in items)
        elev = sum(r["elev_m"] for r in items)
        speeds = [r["avg_kmh"] for r in items if r["avg_kmh"] > 0]
        outdoor = [r for r in items if r["sport"] != "VirtualRide" and r["distance_km"] >= 5]
        # "Long ride" milestone: max distance hit that year
        longest = max(items, key=lambda r: r["distance_km"]) if items else None
        yearly.append({
            "year": y,
            "rides": len(items),
            "outdoor_rides": sum(1 for r in items if r["sport"] != "VirtualRide"),
            "virtual_rides": sum(1 for r in items if r["sport"] == "VirtualRide"),
            "distance_km": round(dist, 1),
            "moving_h": round(time_h, 1),
            "elev_m": round(elev),
            "avg_kmh": round(statistics.fmean(speeds), 2) if speeds else 0,
            "median_kmh": round(statistics.median(speeds), 2) if speeds else 0,
            "p90_kmh": round(statistics.quantiles(speeds, n=10)[-1], 2) if len(speeds) > 10 else (max(speeds) if speeds else 0),
            "longest_km": round(longest["distance_km"], 1) if longest else 0,
            "longest_name": longest["name"] if longest else "",
        })

    # Path/locations: keep only outdoor rides with GPS; downsample paths further if needed.
    paths_for_map = []
    for r in rides:
        if r["sport"] == "VirtualRide" or len(r["path"]) <= 1:
            continue
        mid = r["path"][len(r["path"]) // 2]
        paths_for_map.append({
            "id": r["id"], "year": r["year"], "km": r["distance_km"], "name": r["name"],
            "commute": r["commute"], "workout": r["workout"], "race": r["race"],
            "region": _region(mid[0], mid[1]),
            "path": r["path"],
        })

    total_points = sum(len(p["path"]) for p in paths_for_map)

    region_counts: dict[str, int] = defaultdict(int)
    region_km: dict[str, float] = defaultdict(float)
    for r in rides:
        if r["sport"] == "VirtualRide" or not r["path"]:
            continue
        mid = r["path"][len(r["path"]) // 2]
        reg = _region(mid[0], mid[1])
        region_counts[reg] += 1
        region_km[reg] += r["distance_km"]

    # rolling 30-ride mean of avg_kmh for the progression trend line
    rides_chart = []
    window = []
    for r in rides:
        window.append(r["avg_kmh"])
        if len(window) > 30:
            window.pop(0)
        roll = sum(window) / len(window)
        rides_chart.append({
            "id": r["id"],
            "date": r["start"][:10],
            "sport": r["sport"],
            "km": r["distance_km"],
            "kmh": r["avg_kmh"],
            "elev": r["elev_m"],
            "name": r["name"],
            "commute": r["commute"],
            "workout": r["workout"],
            "year": r["year"],
            "roll_kmh": round(roll, 2),
        })

    payload = {
        "generated_at": rides[-1]["start"] if rides else None,
        "totals": {
            "rides": len(rides),
            "outdoor": sum(1 for r in rides if r["sport"] != "VirtualRide"),
            "virtual": sum(1 for r in rides if r["sport"] == "VirtualRide"),
            "commute": sum(1 for r in rides if r["commute"]),
            "workout": sum(1 for r in rides if r["workout"]),
            "distance_km": round(sum(r["distance_km"] for r in rides), 1),
            "moving_h": round(sum(r["moving_h"] for r in rides), 1),
            "elev_m": round(sum(r["elev_m"] for r in rides)),
            "points": total_points,
        },
        "yearly": yearly,
        "regions": [
            {"name": k, "rides": region_counts[k], "km": round(region_km[k], 1)}
            for k in sorted(region_counts, key=lambda k: -region_km[k])
        ],
        "rides_chart": rides_chart,
        "paths": paths_for_map,
    }
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"wrote {OUT} — {size_mb:.2f} MB, {len(rides)} rides, {total_points} GPS points")
    print("yearly summary:")
    for y in yearly:
        print(f"  {y['year']}: {y['rides']:>3} rides · {y['distance_km']:>7} km · avg {y['avg_kmh']} km/h · longest {y['longest_km']} km")
    print("regions:")
    for r in payload["regions"]:
        print(f"  {r['name']:>13}: {r['rides']:>3} rides · {r['km']:>7} km")


if __name__ == "__main__":
    main()

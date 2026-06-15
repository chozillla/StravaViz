"""Consolidate paginated Strava data into a single payload for the viz."""
from __future__ import annotations
import csv, glob, json, math, statistics, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted((ROOT / "data" / "pages").glob("page-*.json"))
OUT = ROOT / "data" / "rides.json"
# The official Strava bulk export — richer than the MCP (has power, weather, media).
EXPORT_CSV = Path.home() / "Downloads" / "export_43295938" / "activities.csv"
csv.field_size_limit(sys.maxsize)


def load_export() -> dict[str, dict]:
    """Return per-activity-id record from activities.csv if present."""
    if not EXPORT_CSV.exists():
        return {}
    out: dict[str, dict] = {}
    with EXPORT_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            aid = row.get("Activity ID")
            if not aid:
                continue

            def num(key: str) -> float | None:
                v = (row.get(key) or "").strip()
                if not v:
                    return None
                try:
                    return float(v)
                except ValueError:
                    return None

            media = (row.get("Media") or "").strip().strip("|")
            media_files = [m.strip() for m in media.split("|") if m.strip()] if media else []
            out[aid] = {
                "description": (row.get("Activity Description") or "").strip(),
                "avg_watts": num("Average Watts"),
                "max_watts": num("Max Watts"),
                "weighted_watts": num("Weighted Average Power"),
                "avg_hr": num("Average Heart Rate"),
                "max_hr": num("Max Heart Rate"),
                "training_load": num("Training Load"),
                "intensity": num("Intensity"),
                "weather_temp": num("Weather Temperature"),
                "weather_condition": (row.get("Weather Condition") or "").strip(),
                "wind_speed": num("Wind Speed"),
                "precipitation_intensity": num("Precipitation Intensity"),
                "media": media_files,
                "bike": (row.get("Bike") or "").strip(),
            }
    return out

CYCLING = {"Ride", "VirtualRide", "EBikeRide", "MountainBikeRide", "GravelRide", "Velomobile"}
RUNNING = {"Run", "TrailRun", "VirtualRun"}

POWER_DURATIONS = [
    ("pp5s", 5), ("pp15s", 15), ("pp30s", 30),
    ("pp1m", 60), ("pp2m", 120), ("pp3m", 180), ("pp5m", 300), ("pp8m", 480),
    ("pp10m", 600), ("pp15m", 900), ("pp20m", 1200), ("pp30m", 1800),
    ("pp45m", 2700), ("pp1h", 3600),
]


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
    perf_path = ROOT / "data" / "perf" / "_extracted.json"
    perf_by_id: dict[str, dict] = json.loads(perf_path.read_text()) if perf_path.exists() else {}
    export_by_id = load_export()

    # Merge export power data into perf_by_id (export wins when present)
    for aid, ex in export_by_id.items():
        if ex.get("avg_watts") is not None:
            rec = perf_by_id.setdefault(aid, {})
            rec.setdefault("avg_watts", ex["avg_watts"])
            rec.setdefault("avg_hr", ex.get("avg_hr"))
            rec.setdefault("max_hr", ex.get("max_hr"))

    rides = []
    runs: list[dict] = []
    for p in PAGES:
        d = json.loads(p.read_text())
        for a in d["activities"]:
            if a["sport_type"] in RUNNING:
                poly = decode_polyline(a.get("reduced_polyline", ""))
                poly = simplify(poly, every=2)
                s = a["summary"]
                ex = export_by_id.get(a["id"], {})
                pace_min_per_km = (s["moving_time"] / 60) / (s["distance"] / 1000) if s.get("distance") else None
                runs.append({
                    "id": a["id"],
                    "name": a.get("name", ""),
                    "sport": a["sport_type"],
                    "start": a["start_local"],
                    "year": int(a["start_local"][:4]),
                    "distance_km": round(s["distance"] / 1000, 3),
                    "moving_h": round(s["moving_time"] / 3600, 4),
                    "elev_m": round(s.get("elevation_gain") or 0, 1),
                    "avg_kmh": round((s.get("avg_speed") or 0) * 3.6, 2),
                    "pace_min_km": round(pace_min_per_km, 2) if pace_min_per_km else None,
                    "description": ex.get("description") or a.get("description") or "",
                    "media": ex.get("media") or [],
                    "path": [[round(lat, 5), round(lng, 5)] for lat, lng in poly],
                })
                continue
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
            ex = export_by_id.get(a["id"], {})
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
                "description": ex.get("description") or a.get("description") or "",
                "media": ex.get("media") or [],
                "weather": ({
                    "temp": ex.get("weather_temp"),
                    "condition": ex.get("weather_condition") or None,
                    "wind_speed": ex.get("wind_speed"),
                    "precip": ex.get("precipitation_intensity"),
                } if ex.get("weather_temp") is not None else None),
                "bike": ex.get("bike") or None,
                "path": [[round(lat, 5), round(lng, 5)] for lat, lng in poly],
            })

    rides.sort(key=lambda r: r["start"])
    runs.sort(key=lambda r: r["start"])
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
            "date": r["start"][:10],
            "elev": r["elev_m"],
            "avg_kmh": r["avg_kmh"],
            "description": r["description"],
            "media": r["media"],
            "weather": r["weather"],
            "bike": r["bike"],
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

    # ---- Commute PR trend (canonical 14-17 km KBN ↔ CPH commute) ----
    canonical_commutes = [r for r in rides if r["commute"] and 14 <= r["distance_km"] <= 17 and r["sport"] != "VirtualRide"]
    commute_by_month: dict[str, list] = defaultdict(list)
    for r in canonical_commutes:
        commute_by_month[r["start"][:7]].append(r)
    commute_pr = []
    for ym in sorted(commute_by_month):
        items = commute_by_month[ym]
        speeds = sorted(r["avg_kmh"] for r in items)
        best = max(items, key=lambda r: r["avg_kmh"])
        commute_pr.append({
            "month": ym,
            "count": len(items),
            "best_kmh": best["avg_kmh"],
            "best_name": best["name"],
            "best_date": best["start"][:10],
            "median_kmh": speeds[len(speeds) // 2],
        })

    # ---- Power series ----
    power_series = []  # avg watts over time
    for r in rides:
        perf = perf_by_id.get(r["id"])
        if not perf or perf.get("avg_watts") is None:
            continue
        power_series.append({
            "id": r["id"],
            "date": r["start"][:10],
            "name": r["name"],
            "km": r["distance_km"],
            "avg_watts": perf["avg_watts"],
            "avg_hr": perf.get("avg_hr"),
            "max_hr": perf.get("max_hr"),
            "commute": r["commute"],
            "workout": r["workout"],
            "sport": r["sport"],
        })

    # Mean-max power curve (best across all rides for each duration)
    power_curve = []
    for key, secs in POWER_DURATIONS:
        vals = [p.get(key) for p in perf_by_id.values() if p.get(key) is not None]
        if vals:
            power_curve.append({"seconds": secs, "label": key, "watts": max(vals)})

    # ---- Calendar heatmap (per-day load across rides AND runs) ----
    cal_by_day: dict[str, dict] = {}
    for activity in (*rides, *runs):
        d = activity["start"][:10]
        slot = cal_by_day.setdefault(d, {
            "date": d, "km": 0.0, "hours": 0.0, "rides": 0, "runs": 0,
            "ride_km": 0.0, "run_km": 0.0,
        })
        slot["km"] += activity["distance_km"]
        slot["hours"] += activity["moving_h"]
        if activity in runs or activity.get("sport") in RUNNING:
            slot["runs"] += 1
            slot["run_km"] += activity["distance_km"]
        else:
            slot["rides"] += 1
            slot["ride_km"] += activity["distance_km"]
    calendar = sorted(cal_by_day.values(), key=lambda x: x["date"])
    for c in calendar:
        c["km"] = round(c["km"], 1)
        c["hours"] = round(c["hours"], 2)
        c["ride_km"] = round(c["ride_km"], 1)
        c["run_km"] = round(c["run_km"], 1)

    # ---- Photo markers ----
    # Strava strips EXIF GPS from exported photos, so we can't pin them exactly.
    # Best signal we have: stops detected in the .fit.gz stream (see
    # scripts/extract_stops.py). For each ride with photos:
    #   - rank stops by duration (longer = more likely a real photo pause)
    #   - assign photos to the top stops, in path order
    #   - any leftover photos fall back to evenly-spaced path points
    stops_path = ROOT / "data" / "stops.json"
    stops_by_id: dict[str, list[dict]] = json.loads(stops_path.read_text()) if stops_path.exists() else {}

    def make_photo_points(activity: dict, kind: str) -> list[dict]:
        """Generate per-photo markers for a ride or run, placed at detected stops where possible."""
        if not activity["media"] or len(activity["path"]) < 2:
            return []
        if activity["sport"] in ("VirtualRide", "VirtualRun"):
            return []
        n = len(activity["media"])
        stops = stops_by_id.get(activity["id"], [])

        def nearest_path_idx(lat: float, lng: float) -> int:
            best, best_d = 0, float("inf")
            for i, (plat, plng) in enumerate(activity["path"]):
                d = (plat - lat) ** 2 + (plng - lng) ** 2
                if d < best_d:
                    best_d, best = d, i
            return best

        stops_top = sorted(stops, key=lambda s: -s["dur"])[:n]
        for s in stops_top:
            s["path_idx"] = nearest_path_idx(s["lat"], s["lng"])
        stops_top.sort(key=lambda s: s["path_idx"])

        points = []
        for i, media_path in enumerate(activity["media"]):
            if i < len(stops_top):
                lat, lng = stops_top[i]["lat"], stops_top[i]["lng"]
                source = "stop"
            else:
                idx = int(round((i + 1) / (n + 1) * (len(activity["path"]) - 1)))
                lat, lng = activity["path"][idx]
                source = "path"
            points.append({
                "ride_id": activity["id"],
                "ride_name": activity["name"],
                "date": activity["start"][:10],
                "year": activity["year"],
                "lat": lat,
                "lng": lng,
                "media": media_path,
                "is_video": media_path.lower().endswith((".mp4", ".mov", ".m4v")),
                "n_in_ride": n,
                "source": source,
                "kind": kind,
            })
        return points

    photo_points = []
    for r in rides:
        photo_points.extend(make_photo_points(r, "ride"))
    for r in runs:
        photo_points.extend(make_photo_points(r, "run"))

    # ---- Weather × pace ----
    weather_rides = []
    for r in rides:
        # Only outdoor cycling rides with a known temperature and a meaningful avg speed
        if r["sport"] == "VirtualRide":
            continue
        ex_temp = None
        # The weather temp is on the rich record — pull from rides via export merge.
        # We saved it on the ride dict only via paths; recompute here from export_by_id.
        ex = export_by_id.get(r["id"], {})
        if ex.get("weather_temp") is None:
            continue
        if r["avg_kmh"] < 5:
            continue
        weather_rides.append({
            "id": r["id"],
            "date": r["start"][:10],
            "name": r["name"],
            "km": r["distance_km"],
            "kmh": r["avg_kmh"],
            "temp": ex["weather_temp"],
            "wind": ex.get("wind_speed"),
            "precip": ex.get("precipitation_intensity") or 0,
            "condition": ex.get("weather_condition") or "",
        })

    # Bucket by temperature for aggregate
    buckets = [(-10, 0), (0, 5), (5, 10), (10, 15), (15, 20), (20, 25), (25, 35)]
    weather_buckets = []
    for lo, hi in buckets:
        items = [w for w in weather_rides if lo <= w["temp"] < hi]
        if not items:
            continue
        speeds = sorted(w["kmh"] for w in items)
        weather_buckets.append({
            "lo": lo, "hi": hi, "count": len(items),
            "median_kmh": round(speeds[len(speeds) // 2], 2),
            "p10_kmh": round(speeds[int(len(speeds) * 0.1)], 2),
            "p90_kmh": round(speeds[int(len(speeds) * 0.9)], 2),
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
        "runs_chart": [
            {
                "id": r["id"],
                "date": r["start"][:10],
                "year": r["year"],
                "sport": r["sport"],
                "km": r["distance_km"],
                "kmh": r["avg_kmh"],
                "pace_min_km": r["pace_min_km"],
                "elev": r["elev_m"],
                "name": r["name"],
            }
            for r in runs
        ],
        "runs_totals": {
            "count": len(runs),
            "distance_km": round(sum(r["distance_km"] for r in runs), 1),
            "moving_h": round(sum(r["moving_h"] for r in runs), 1),
            "elev_m": round(sum(r["elev_m"] for r in runs)),
        },
        "runs_yearly": [
            {
                "year": y,
                "runs": len(items),
                "distance_km": round(sum(r["distance_km"] for r in items), 1),
                "moving_h": round(sum(r["moving_h"] for r in items), 1),
                "median_pace": round(statistics.median([r["pace_min_km"] for r in items if r["pace_min_km"]]), 2)
                    if any(r["pace_min_km"] for r in items) else None,
                "longest_km": round(max(r["distance_km"] for r in items), 1) if items else 0,
            }
            for y, items in sorted({y: [r for r in runs if r["year"] == y] for y in {r["year"] for r in runs}}.items())
        ],
        "run_paths": [
            {
                "id": r["id"], "year": r["year"], "km": r["distance_km"], "name": r["name"],
                "date": r["start"][:10], "pace_min_km": r["pace_min_km"], "elev": r["elev_m"],
                "media": r["media"], "description": r["description"],
                "path": r["path"],
            }
            for r in runs
            if r["sport"] != "VirtualRun" and len(r["path"]) > 1
        ],
        "rides_chart": rides_chart,
        "commute_pr": commute_pr,
        "calendar": calendar,
        "power_series": power_series,
        "power_curve": power_curve,
        "power_sample_size": len(perf_by_id),
        "weather_rides": weather_rides,
        "weather_buckets": weather_buckets,
        "photo_points": photo_points,
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

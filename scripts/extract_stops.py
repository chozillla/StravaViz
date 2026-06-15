"""Parse .fit.gz files for rides that have media, find low-speed "stops", and
emit a per-activity list of stop locations. We later use these to place photos
at likely actual capture points (Strava export strips EXIF GPS/time, so this is
the closest signal we have for "where on the ride a photo was probably taken").

Output: data/stops.json — { activity_id: [[lat, lng], ...] }

Run via the venv that has fitparse installed:
    /tmp/stravaviz_venv/bin/python scripts/extract_stops.py
"""
from __future__ import annotations
import csv, gzip, io, json, sys
from pathlib import Path

import fitparse  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
EXPORT = Path.home() / "Downloads" / "export_43295938"
ACTIVITIES_DIR = EXPORT / "activities"
ACTIVITIES_CSV = EXPORT / "activities.csv"
OUT = ROOT / "data" / "stops.json"

# A "stop" = at least STOP_MIN_SECS consecutive seconds where speed < STOP_MAX_MPS.
# After a stop, we require resumed-motion of at least RESUME_SECS at higher speed
# before we'll count a new stop (so a single long stop isn't double-counted).
STOP_MAX_MPS = 1.5     # ~5.4 km/h — stationary or briefly off-bike
STOP_MIN_SECS = 5      # real but brief pause (photo, traffic light, look at map)
RESUME_SECS = 6        # require this much motion before a new stop counts

SEMICIRCLE = 2 ** 31 / 180.0


def to_deg(sc: int | None) -> float | None:
    if sc is None:
        return None
    return sc / SEMICIRCLE


def find_stops(fit_path: Path) -> list[dict]:
    """Return list of {lat, lng, duration_s} for each detected stop."""
    with fit_path.open("rb") as fh, gzip.GzipFile(fileobj=fh) as gz:
        fit = fitparse.FitFile(io.BytesIO(gz.read()))
        records = list(fit.get_messages("record"))

    stops: list[dict] = []
    in_stop = False
    stop_buf: list[tuple[float, float]] = []
    moving_run = 0
    for r in records:
        d = {f.name: f.value for f in r}
        lat = to_deg(d.get("position_lat"))
        lng = to_deg(d.get("position_long"))
        speed = d.get("enhanced_speed") if d.get("enhanced_speed") is not None else d.get("speed")
        if lat is None or lng is None or speed is None:
            continue
        if speed < STOP_MAX_MPS:
            stop_buf.append((lat, lng))
            in_stop = True
            moving_run = 0
        else:
            moving_run += 1
            if in_stop and moving_run >= RESUME_SECS:
                # finalize this stop
                if len(stop_buf) >= STOP_MIN_SECS:
                    mid = stop_buf[len(stop_buf) // 2]
                    stops.append({"lat": mid[0], "lng": mid[1], "dur": len(stop_buf)})
                stop_buf = []
                in_stop = False
    if in_stop and len(stop_buf) >= STOP_MIN_SECS:
        mid = stop_buf[len(stop_buf) // 2]
        stops.append({"lat": mid[0], "lng": mid[1], "dur": len(stop_buf)})
    return stops


def main() -> None:
    # Find activities with media; we only bother parsing those.
    csv.field_size_limit(sys.maxsize)
    targets: list[tuple[str, Path]] = []
    with ACTIVITIES_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            if not (row.get("Media") or "").strip().strip("|"):
                continue
            if row["Activity Type"] not in ("Ride", "Virtual Ride", "Run", "Trail Run"):
                continue
            fname = (row.get("Filename") or "").strip()
            if not fname:
                continue
            p = EXPORT / fname
            if not p.exists() or not p.name.endswith(".fit.gz"):
                continue
            targets.append((row["Activity ID"], p))

    print(f"will parse {len(targets)} activities")
    out: dict[str, list[list[float]]] = {}
    for i, (aid, p) in enumerate(targets, 1):
        try:
            stops = find_stops(p)
        except Exception as e:
            print(f"  [{i}/{len(targets)}] {aid}: parse failed — {e}")
            continue
        out[aid] = [
            {"lat": round(s["lat"], 5), "lng": round(s["lng"], 5), "dur": s["dur"]}
            for s in stops
        ]
        if i % 25 == 0 or i == len(targets):
            print(f"  [{i}/{len(targets)}] {aid}: {len(stops)} stops")
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    counts = [len(v) for v in out.values()]
    if counts:
        counts.sort()
        print(f"wrote {OUT}: {len(out)} activities, median {counts[len(counts)//2]} stops/ride, max {counts[-1]}")


if __name__ == "__main__":
    main()

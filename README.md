# StravaViz

A personal project to turn my Strava data into something I actually look at.

Strava's own dashboards are fine for logging activities, but they're not built for *thinking* about training — they show you what you did, not what it means. StravaViz is a UI/UX-first attempt to fix that: fewer numbers, more answers.

## Goals

- **Insight over inventory.** Every view should answer a question I'd actually ask ("am I getting faster?", "where do I always slow down?", "what does a good week look like?"), not just list activities.
- **Glanceable.** The most useful screens should be understandable in under five seconds.
- **Honest.** No vanity metrics. If a trend isn't real, don't draw a line through it.
- **Mine.** Tuned for how I train, not a generic athlete dashboard.

## Planned views

A rough map of what I want to build, roughly in priority order:

- **Training pulse** — a single screen that answers "how am I doing lately?" Volume, intensity, and consistency over the last 4–8 weeks vs. the prior period.
- **Route heatmap** — every GPS trace overlaid, so the city lights up where I actually run/ride. Hover a segment to see how often and how fast.
- **Pace-vs-effort** — pace plotted against heart rate / grade over time, to see whether I'm getting faster or just trying harder.
- **Segment deep-dives** — for routes I repeat, a small-multiples view of every attempt: where I sped up, where I died.
- **Calendar grid** — a year-at-a-glance with each day shaded by load, so streaks and gaps are obvious.
- **Activity drilldown** — the one-activity view, redesigned. Splits, elevation, HR zones, and weather, on one screen, without scrolling.

## Design principles

- One question per view. If a chart needs a paragraph to read, it's the wrong chart.
- Color carries meaning, not decoration. Reserve hue for things like effort, pace bands, or recency.
- Small multiples over dashboards-of-dashboards.
- Mobile-readable. I check this on my phone after a run.

## Stack

Python-based — exact tooling TBD as I prototype. Likely candidates: a notebook environment (Marimo or Jupyter) for exploration, and either Streamlit or a small custom frontend for the polished views. Data pulled from the Strava API.

## Status

Early. Repo is fresh; visualizations are being sketched and prototyped.

## License

MIT — see [LICENSE](LICENSE).

# Simple Time Tracker — Streamlit

Track how much time you spend on all the useless activities in the world — in the browser.

A toy project built for a Claude Code workshop, reimplementing
[Android-SimpleTimeTracker](https://github.com/Razeeman/Android-SimpleTimeTracker) by
[Razeeman](https://github.com/Razeeman) as a Streamlit app.

## Running it

```bash
git clone https://github.com/exdatic/timetracker.git
cd timetracker
pip install -r requirements.txt
streamlit run app.py
```

The first launch offers to load demo data. Everything is stored in a SQLite file at
`data/timetracker.db`; set `TIMETRACKER_DB` to use a different one.

## What it does

- **Timers** — start and stop activities, live tick, goal progress, add records after the fact
- **Records** — browse, edit and delete records for any range, with a day timeline and filters
- **Statistics** — time per activity, category or tag, with per-day and time-of-day breakdowns
- **Goals** — daily, weekly, monthly or per-session goals and limits, by duration or count
- **Activities** — activities, categories and tags
- **Settings** — preferences, JSON backup and restore, CSV export, demo data

## Tests

```bash
pip install -e ".[dev]"
pytest -q
flake8 .
```

## License

[GPL-3.0](LICENSE), following the license of the original app this one is based on.

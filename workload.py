"""Measure real historical batch replay and verify recovery; no cloud/SLA claim."""

import argparse
import json
import platform
import sqlite3
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from pipeline import run


def measure(source, repeats):
    if not 1 <= repeats <= 100:
        raise ValueError("repeats must be between 1 and 100")
    timings, cached_timings = [], []
    with tempfile.TemporaryDirectory() as scratch:
        for index in range(repeats):
            database = Path(scratch) / f"batch-{index}.sqlite"
            start = time.perf_counter()
            report, cached = run(source, database)
            timings.append(time.perf_counter() - start)
            if cached:
                raise AssertionError("Fresh database unexpectedly cached")
            start = time.perf_counter()
            replay, cached = run(source, database)
            cached_timings.append(time.perf_counter() - start)
            if not cached or replay != report:
                raise AssertionError("Replay changed audit or missed cache")
            invalid = Path(scratch) / "invalid.csv"
            invalid.write_text("wrong_schema\n1\n")
            try:
                run(invalid, database)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid schema accepted")
            with sqlite3.connect(database) as connection:
                rows, rentals = connection.execute(
                    "SELECT COUNT(*), SUM(cnt) FROM observations"
                ).fetchone()
            if (rows, rentals) != (report["accepted_rows"], report["rentals"]):
                raise AssertionError("Failed batch damaged active snapshot")
    return {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Local historical batch replay; not live traffic or cloud operation",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "source_sha256": report["source_sha256"],
        "repeats": repeats,
        "rows_per_batch": report["input_rows"],
        "fresh_load_seconds": timings,
        "cached_replay_seconds": cached_timings,
        "median_fresh_rows_per_second": report["input_rows"]
        / statistics.median(timings),
        "verified": ["deterministic replay", "invalid-schema snapshot preservation"],
        "limitations": [
            "Same historical input repeated; no new independent observations",
            "Single process, local disk, whole-file memory use",
            "Cached replay still parses and validates the entire input",
            "No concurrency, network latency, cloud cost, or uptime measurement",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/hour.csv")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", default="results/workload.json")
    args = parser.parse_args()
    result = measure(args.input, args.repeats)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))

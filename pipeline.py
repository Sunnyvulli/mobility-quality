"""Auditable batch pipeline for historical UCI bike-sharing observations."""

import argparse, csv, hashlib, io, json, sqlite3, time
from collections import Counter
from datetime import date
from pathlib import Path

FIELDS = [
    "instant",
    "dteday",
    "season",
    "yr",
    "mnth",
    "hr",
    "holiday",
    "weekday",
    "workingday",
    "weathersit",
    "temp",
    "atemp",
    "hum",
    "windspeed",
    "casual",
    "registered",
    "cnt",
]
INTEGER = set(FIELDS) - {"dteday", "temp", "atemp", "hum", "windspeed"}
RANGES = {
    "season": (1, 4),
    "yr": (0, 1),
    "mnth": (1, 12),
    "hr": (0, 23),
    "holiday": (0, 1),
    "weekday": (0, 6),
    "workingday": (0, 1),
    "weathersit": (1, 4),
    "temp": (0, 1),
    "atemp": (0, 1),
    "hum": (0, 1),
    "windspeed": (0, 1),
}


def validate(rows, semantic=True):
    accepted, rejected, keys, ids = [], [], set(), set()
    for line, raw in enumerate(rows, 2):
        reasons, row = [], {}
        try:
            for k in FIELDS:
                row[k] = (
                    raw[k]
                    if k == "dteday"
                    else (int(raw[k]) if k in INTEGER else float(raw[k]))
                )
            day = date.fromisoformat(row["dteday"])
            for k, (low, high) in RANGES.items():
                if not low <= row[k] <= high:
                    reasons.append("range:" + k)
            for k in ["instant", "casual", "registered", "cnt"]:
                if row[k] < (1 if k == "instant" else 0):
                    reasons.append("range:" + k)
            if semantic:
                if row["cnt"] != row["casual"] + row["registered"]:
                    reasons.append("count_reconciliation")
                if (
                    row["yr"] != day.year - 2011
                    or row["mnth"] != day.month
                    or row["weekday"] != (day.weekday() + 1) % 7
                ):
                    reasons.append("calendar_reconciliation")
                if (row["dteday"], row["hr"]) in keys or row["instant"] in ids:
                    reasons.append("duplicate_key")
        except (ValueError, TypeError, KeyError, OverflowError):
            reasons.append("schema_or_parse")
        if reasons:
            rejected.append(
                {"line": line, "instant": raw.get("instant"), "reasons": reasons}
            )
        else:
            accepted.append(row)
            keys.add((row["dteday"], row["hr"]))
            ids.add(row["instant"])
    return accepted, rejected


def run(source, db_path):
    start = time.perf_counter()
    source = Path(source)
    # Hash and parse one captured byte sequence, even if the path is replaced.
    source_bytes = source.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    reader = csv.DictReader(io.StringIO(source_bytes.decode("utf-8"), newline=""))
    if reader.fieldnames != FIELDS:
        raise ValueError("Unexpected schema; prior snapshot preserved")
    rows = list(reader)
    accepted, rejected = validate(rows)
    if not accepted:
        raise ValueError("No valid records; prior snapshot preserved")
    with sqlite3.connect(db_path) as db:
        # Keep the cache check and any replacement under one writer transaction.
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE IF NOT EXISTS observations (instant INTEGER PRIMARY KEY,dteday TEXT,season INTEGER,yr INTEGER,mnth INTEGER,hr INTEGER,holiday INTEGER,weekday INTEGER,workingday INTEGER,weathersit INTEGER,temp REAL,atemp REAL,hum REAL,windspeed REAL,casual INTEGER,registered INTEGER,cnt INTEGER,UNIQUE(dteday,hr))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS batch_manifest (sha256 TEXT PRIMARY KEY,report_json TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS active_snapshot (singleton INTEGER PRIMARY KEY CHECK(singleton=1),sha256 TEXT)"
        )
        cached = db.execute(
            "SELECT report_json FROM batch_manifest WHERE sha256=?", (digest,)
        ).fetchone()
        active = db.execute(
            "SELECT sha256 FROM active_snapshot WHERE singleton=1"
        ).fetchone()
        expected = [tuple(row[k] for k in FIELDS) for row in accepted]
        columns = ",".join(FIELDS)
        snapshot_matches = (
            cached
            and active
            and active[0] == digest
            and db.execute(
                f"SELECT {columns} FROM observations ORDER BY instant"
            ).fetchall()
            == sorted(expected, key=lambda row: row[0])
        )
        if snapshot_matches:
            return json.loads(cached[0]), True
        db.execute("DELETE FROM observations")
        db.executemany(
            "INSERT INTO observations VALUES (" + ",".join("?" for _ in FIELDS) + ")",
            expected,
        )
        daily = [
            {"date": d, "observed_hours": n, "rentals": v}
            for d, n, v in db.execute(
                "SELECT dteday,COUNT(*),SUM(cnt) FROM observations GROUP BY dteday ORDER BY dteday"
            )
        ]
        report = {
            "source_sha256": digest,
            "input_rows": len(rows),
            "accepted_rows": len(accepted),
            "rejected_rows": len(rejected),
            "reason_counts": dict(Counter(x for r in rejected for x in r["reasons"])),
            "quarantine": rejected,
            "observed_days": len(daily),
            "missing_hours_in_observed_days": sum(
                24 - r["observed_hours"] for r in daily
            ),
            "rentals": sum(r["rentals"] for r in daily),
            "daily": daily,
            "elapsed_seconds": round(time.perf_counter() - start, 6),
        }
        db.execute(
            "INSERT OR REPLACE INTO batch_manifest VALUES (?,?)",
            (digest, json.dumps(report, sort_keys=True)),
        )
        db.execute("INSERT OR REPLACE INTO active_snapshot VALUES (1,?)", (digest,))
    return report, False


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/hour.csv")
    p.add_argument("--database", default="mobility.sqlite")
    p.add_argument("--output", default="results/pipeline.json")
    a = p.parse_args()
    r, s = run(a.input, a.database)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(r, indent=2) + "\n")
    print(json.dumps({k: v for k, v in r.items() if k not in ["daily", "quarantine"]}))
    print("cached:", s)

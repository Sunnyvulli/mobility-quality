"""Run an isolated, dependency-free smoke demonstration from a fresh checkout."""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT


def main():
    start = time.perf_counter()
    test_count = unittest.defaultTestLoader.discover(str(PROJECT)).countTestCases()
    with tempfile.TemporaryDirectory(prefix="mobility-demo-") as tmp:
        database = Path(tmp) / "demo.sqlite"
        report = Path(tmp) / "report.json"
        command = [
            sys.executable,
            str(PROJECT / "pipeline.py"),
            "--input",
            str(PROJECT / "data/hour.csv"),
            "--database",
            str(database),
            "--output",
            str(report),
        ]
        subprocess.run(command, check=True, cwd=PROJECT)
        subprocess.run(command, check=True, cwd=PROJECT)
        result = json.loads(report.read_text())
        assert result["accepted_rows"] == 17379
        assert result["rentals"] == 3292679
        subprocess.run(
            [sys.executable, "-m", "unittest", "-v"], check=True, cwd=PROJECT
        )
    print(
        json.dumps(
            {
                "status": "passed",
                "accepted_rows": result["accepted_rows"],
                "rentals": result["rentals"],
                "tests": test_count,
                "elapsed_seconds": round(time.perf_counter() - start, 3),
                "python": sys.version.split()[0],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

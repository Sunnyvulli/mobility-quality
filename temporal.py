"""Whole-day, expanding-window backtest with online-available weekly lag."""

import csv
import hashlib
import json
import platform
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

FEATURES = ["season", "yr", "mnth", "hr", "holiday", "weekday", "workingday"]
STARTS = ["2012-04-01", "2012-07-01", "2012-10-01"]
SEEDS = [11, 23, 37]


def read_rows(path):
    with Path(path).open(newline="") as handle:
        raw = list(csv.DictReader(handle))
    rows = []
    for row in raw:
        parsed = {key: int(row[key]) for key in FEATURES + ["cnt"]}
        parsed["timestamp"] = datetime.fromisoformat(row["dteday"]) + timedelta(
            hours=parsed["hr"]
        )
        rows.append(parsed)
    return sorted(rows, key=lambda row: row["timestamp"])


def partition(rows, start, days=28):
    boundary = datetime.fromisoformat(start)
    end = boundary + timedelta(days=days)
    train = [row for row in rows if row["timestamp"] < boundary]
    test = [row for row in rows if boundary <= row["timestamp"] < end]
    if not train or not test:
        raise ValueError("Both training and evaluation windows must be non-empty")
    return train, test


def seasonal_predictions(rows, train, test):
    # Online one-hour-ahead protocol: a count from seven days earlier is known.
    # This is intentionally not a fixed 28-day-ahead forecast.
    observed = {row["timestamp"]: row["cnt"] for row in rows}
    grouped = defaultdict(list)
    for row in train:
        grouped[(row["timestamp"].weekday(), row["hr"])].append(row["cnt"])
    overall = sum(row["cnt"] for row in train) / len(train)
    predictions, fallbacks = [], 0
    for row in test:
        lag = row["timestamp"] - timedelta(days=7)
        if lag in observed:
            predictions.append(float(observed[lag]))
        else:
            values = grouped[(row["timestamp"].weekday(), row["hr"])]
            predictions.append(sum(values) / len(values) if values else overall)
            fallbacks += 1
    return predictions, fallbacks


def evaluate(root):
    import numpy as np
    import pandas as pd
    import sklearn
    from sklearn.ensemble import RandomForestRegressor

    source = root / "data/hour.csv"
    rows = read_rows(source)
    metrics, daily_errors, boundaries = [], [], []
    for start in STARTS:
        train, test = partition(rows, start)
        x_train = [[row[key] for key in FEATURES] for row in train]
        x_test = [[row[key] for key in FEATURES] for row in test]
        y_train = np.array([row["cnt"] for row in train])
        actual = np.array([row["cnt"] for row in test])
        weekly, missing = seasonal_predictions(rows, train, test)
        boundaries.append(
            {
                "start": start,
                "end_exclusive": (
                    datetime.fromisoformat(start) + timedelta(days=28)
                ).isoformat(),
                "train_max": train[-1]["timestamp"].isoformat(),
                "train_rows": len(train),
                "test_rows": len(test),
                "test_days": len({row["timestamp"].date() for row in test}),
                "weekly_lag_fallbacks": missing,
            }
        )
        predictions = {
            "train_mean": np.repeat(y_train.mean(), len(test)),
            "weekly_lag_online": np.array(weekly),
        }
        forest_errors = []
        for seed in SEEDS:
            forest = RandomForestRegressor(
                n_estimators=60,
                max_depth=16,
                min_samples_leaf=2,
                random_state=seed,
                n_jobs=1,
            )
            forest.fit(x_train, y_train)
            pred = forest.predict(x_test)
            error = np.abs(actual - pred)
            forest_errors.append(error)
            metrics.append(
                {
                    "start": start,
                    "model": "calendar_forest",
                    "seed": seed,
                    "rows": len(test),
                    "mae": float(error.mean()),
                    "rmse": float(np.sqrt(np.mean((actual - pred) ** 2))),
                }
            )
        predictions["calendar_forest_seed_mean_error"] = np.mean(forest_errors, axis=0)
        for name in ["train_mean", "weekly_lag_online"]:
            pred = predictions[name]
            metrics.append(
                {
                    "start": start,
                    "model": name,
                    "seed": None,
                    "rows": len(test),
                    "mae": float(np.abs(actual - pred).mean()),
                    "rmse": float(np.sqrt(np.mean((actual - pred) ** 2))),
                }
            )
        for index, row in enumerate(test):
            daily_errors.append(
                {
                    "fold": start,
                    "day": row["timestamp"].date().isoformat(),
                    "forest_abs_error": float(
                        predictions["calendar_forest_seed_mean_error"][index]
                    ),
                    "weekly_abs_error": float(abs(actual[index] - weekly[index])),
                }
            )
    frame = pd.DataFrame(metrics)
    summary = []
    for name, group in frame.groupby("model"):
        summary.append(
            {
                "model": name,
                "weighted_mae": float(np.average(group.mae, weights=group.rows)),
                "weighted_rmse": float(
                    np.sqrt(np.average(group.rmse**2, weights=group.rows))
                ),
                "runs": len(group),
            }
        )
    day = (
        pd.DataFrame(daily_errors)
        .groupby(["fold", "day"])
        .agg(
            forest_abs_error=("forest_abs_error", "mean"),
            weekly_abs_error=("weekly_abs_error", "mean"),
        )
        .reset_index()
    )
    differences = (day.forest_abs_error - day.weekly_abs_error).to_numpy()
    rng = np.random.default_rng(101)
    bootstrap = np.array(
        [
            rng.choice(differences, len(differences), replace=True).mean()
            for _ in range(2000)
        ]
    )
    output = {
        "protocol": "Online one-hour-ahead comparison, models refreshed at each 28-day fold boundary; observed seven-day-old counts available during each test window",
        "features": FEATURES,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "sklearn": sklearn.__version__,
        "seeds": SEEDS,
        "folds": boundaries,
        "metrics": metrics,
        "summary": summary,
        "daily_bootstrap": {
            "unit": "observed day, equally weighted across folds",
            "days": len(day),
            "replicates": 2000,
            "seed": 101,
            "mean_difference_forest_minus_weekly": float(differences.mean()),
            "percentile_95_interval": np.quantile(bootstrap, [0.025, 0.975]).tolist(),
            "limitation": "Exploratory interval assumes exchangeable days; temporal dependence and overlapping training windows are not modeled",
        },
    }
    (root / "results/temporal-evaluation.json").write_text(
        json.dumps(output, indent=2) + "\n"
    )
    day.to_csv(root / "results/temporal-daily-errors.csv", index=False)
    print(
        json.dumps(
            {
                "summary": summary,
                "daily_bootstrap": output["daily_bootstrap"],
                "folds": boundaries,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    evaluate(Path(__file__).resolve().parent)

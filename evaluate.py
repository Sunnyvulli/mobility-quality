"""Retrospective estimation; observed weather is not a future-weather forecast."""

import csv, hashlib, json, platform, time
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.dummy import DummyRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from pipeline import validate

p = Path(__file__).parent
df = (
    pd.read_csv(p / "data/hour.csv")
    .sort_values(["dteday", "hr"])
    .reset_index(drop=True)
)
features = [
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
]
results = []
for seed in [11, 23, 37]:
    indices = np.arange(len(df))
    cut = int(0.8 * len(df))
    for split in ["chronological", "random"]:
        tr, te = (
            (indices[:cut], indices[cut:])
            if split == "chronological"
            else train_test_split(indices, test_size=0.2, random_state=seed)
        )
        for name in ["mean", "forest", "leakage_positive_control"]:
            cols = features + (
                ["casual", "registered"] if name == "leakage_positive_control" else []
            )
            model = (
                DummyRegressor()
                if name == "mean"
                else RandomForestRegressor(
                    n_estimators=60,
                    max_depth=16,
                    min_samples_leaf=2,
                    random_state=seed,
                    n_jobs=1,
                )
            )
            t = time.perf_counter()
            model.fit(df.iloc[tr][cols], df.iloc[tr]["cnt"])
            pred = model.predict(df.iloc[te][cols])
            results.append(
                {
                    "seed": seed,
                    "split": split,
                    "model": name,
                    "train_rows": len(tr),
                    "test_rows": len(te),
                    "mae": float(mean_absolute_error(df.iloc[te]["cnt"], pred)),
                    "rmse": float(
                        np.sqrt(mean_squared_error(df.iloc[te]["cnt"], pred))
                    ),
                    "seconds": time.perf_counter() - t,
                }
            )
with (p / "data/hour.csv").open() as f:
    raw = list(csv.DictReader(f))
faults = []
for seed in [11, 23, 37]:
    for rate in [0.01, 0.05, 0.1]:
        rng = np.random.default_rng(seed)
        n = int(len(raw) * rate)
        chosen = rng.choice(len(raw), n, replace=False)
        for fault in ["invalid_hour", "count_mismatch", "duplicate"]:
            rows = [r.copy() for r in raw]
            if fault == "duplicate":
                rows += [raw[i].copy() for i in chosen]
                truth = set(range(len(raw), len(rows)))
            else:
                truth = set(map(int, chosen))
                for i in chosen:
                    if fault == "invalid_hour":
                        rows[i]["hr"] = "25"
                    else:
                        rows[i]["cnt"] = str(int(rows[i]["cnt"]) + 100)
            for policy in ["domain_only", "semantic_and_key"]:
                good, bad = validate(rows, semantic=policy == "semantic_and_key")
                flagged = {r["line"] - 2 for r in bad}
                tp = len(flagged & truth)
                fp = len(flagged - truth)
                faults.append(
                    {
                        "seed": seed,
                        "rate": rate,
                        "fault": fault,
                        "policy": policy,
                        "injected_rows": len(truth),
                        "detected": tp,
                        "false_positives": fp,
                        "recall": tp / len(truth),
                        "aggregate_error": sum(r["cnt"] for r in good)
                        - int(df.cnt.sum()),
                    }
                )
output = {
    "dataset_sha256": hashlib.sha256((p / "data/hour.csv").read_bytes()).hexdigest(),
    "rows": len(df),
    "features": features,
    "target": "cnt",
    "seeds": [11, 23, 37],
    "python": platform.python_version(),
    "numpy": np.__version__,
    "pandas": pd.__version__,
    "sklearn": sklearn.__version__,
    "prediction": results,
    "fault_injection": faults,
}
(p / "results/evaluation.json").write_text(json.dumps(output, indent=2) + "\n")
summary = (
    pd.DataFrame(results)
    .groupby(["split", "model"])
    .agg(mae_mean=("mae", "mean"), mae_sd=("mae", "std"), rmse_mean=("rmse", "mean"))
    .round(3)
)
print(summary.to_string())
summary.to_csv(p / "results/model-summary.csv")
pd.DataFrame(faults).groupby(["fault", "policy"]).agg(
    recall=("recall", "mean"), false_positives=("false_positives", "sum")
).to_csv(p / "results/fault-summary.csv")

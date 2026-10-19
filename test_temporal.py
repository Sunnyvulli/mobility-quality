import unittest
from datetime import datetime, timedelta
from pathlib import Path
from temporal import partition, read_rows, seasonal_predictions


class TemporalProtocolTests(unittest.TestCase):
    def test_real_windows_use_whole_days_and_only_past_training(self):
        rows = read_rows(Path(__file__).parent / "data/hour.csv")
        observed = set()
        for start in ["2012-04-01", "2012-07-01", "2012-10-01"]:
            train, test = partition(rows, start)
            boundary = datetime.fromisoformat(start)
            self.assertLess(max(row["timestamp"] for row in train), boundary)
            days = {row["timestamp"].date() for row in test}
            self.assertEqual(len(days), 28)
            self.assertFalse(days & observed)
            observed |= days
            self.assertTrue(
                all(
                    boundary <= row["timestamp"] < boundary + timedelta(days=28)
                    for row in test
                )
            )

    def test_weekly_lag_uses_past_observation_not_current_target(self):
        origin = datetime(2012, 1, 1)
        rows = [
            {"timestamp": origin + timedelta(days=i), "hr": 0, "cnt": i + 10}
            for i in range(15)
        ]
        train, test = rows[:7], rows[7:8]
        pred, fallbacks = seasonal_predictions(rows, train, test)
        self.assertEqual(pred, [10.0])
        self.assertEqual(fallbacks, 0)
        rows[7]["cnt"] = 999999
        changed, _ = seasonal_predictions(rows, train, test)
        self.assertEqual(changed, pred)

    def test_missing_weekly_lag_falls_back_to_training_only(self):
        origin = datetime(2012, 1, 1)
        train = [{"timestamp": origin, "hr": 0, "cnt": 12}]
        test = [{"timestamp": origin + timedelta(days=14), "hr": 0, "cnt": 9999}]
        pred, fallbacks = seasonal_predictions(train + test, train, test)
        self.assertEqual(pred, [12.0])
        self.assertEqual(fallbacks, 1)


if __name__ == "__main__":
    unittest.main()

import csv, json, sqlite3, tempfile, unittest, threading, urllib.request, urllib.error
from pathlib import Path
from http.server import HTTPServer
from unittest.mock import patch
import hashlib
from pipeline import run, validate, FIELDS
from api import Handler


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "m.sqlite"
        self.source = Path(__file__).parent / "data/hour.csv"
        with self.source.open() as f:
            self.raw = list(csv.DictReader(f))

    def test_real_data_reconciles(self):
        r, s = run(self.source, self.db)
        self.assertFalse(s)
        self.assertEqual(r["input_rows"], 17379)
        self.assertEqual(r["accepted_rows"] + r["rejected_rows"], 17379)
        self.assertEqual(r["rejected_rows"], 0)
        self.assertEqual(r["rentals"], sum(int(x["cnt"]) for x in self.raw))

    def test_cache_is_idempotent(self):
        a, _ = run(self.source, self.db)
        b, s = run(self.source, self.db)
        self.assertTrue(s)
        self.assertEqual(a, b)

    def test_cache_repairs_modified_deleted_and_extra_observations(self):
        original, _ = run(self.source, self.db)
        with sqlite3.connect(self.db) as db:
            expected_rows = db.execute(
                "SELECT * FROM observations ORDER BY instant"
            ).fetchall()
        mutations = [
            "UPDATE observations SET cnt=cnt+1 WHERE instant=1",
            "UPDATE observations SET hum=hum-0.001 WHERE instant=1",
            "DELETE FROM observations WHERE instant=1",
            "INSERT INTO observations SELECT instant+100000,dteday||'x',season,yr,mnth,hr,holiday,weekday,workingday,weathersit,temp,atemp,hum,windspeed,casual,registered,cnt FROM observations WHERE instant=1",
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with sqlite3.connect(self.db) as db:
                    self.assertEqual(
                        db.execute(
                            "SELECT * FROM observations ORDER BY instant"
                        ).fetchall(),
                        expected_rows,
                    )
                    db.execute(mutation)
                repaired, cached = run(self.source, self.db)
                self.assertFalse(cached)
                self.assertEqual(repaired["source_sha256"], original["source_sha256"])
                with sqlite3.connect(self.db) as db:
                    self.assertEqual(
                        db.execute(
                            "SELECT * FROM observations ORDER BY instant"
                        ).fetchall(),
                        expected_rows,
                    )
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*),SUM(cnt) FROM observations"
                        ).fetchone(),
                        (17379, 3292679),
                    )
                replay, cached = run(self.source, self.db)
                self.assertTrue(cached)
                self.assertEqual(replay, repaired)

    def test_hash_and_rows_use_same_source_bytes(self):
        source = Path(self.tmp.name) / "changing.csv"
        original = self.source.read_bytes()
        source.write_bytes(original)
        read_bytes = Path.read_bytes

        def replace_after_read(path):
            captured = read_bytes(path)
            if path == source:
                path.write_text("wrong_schema\n1\n")
            return captured

        with patch.object(Path, "read_bytes", replace_after_read):
            report, _ = run(source, self.db)
        self.assertEqual(report["source_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(report["accepted_rows"], 17379)

    def test_failed_replacement_rolls_back_rows_and_manifest(self):
        original, _ = run(self.source, self.db)
        replacement = Path(self.tmp.name) / "replacement.csv"
        with replacement.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(self.raw[:2])
        with sqlite3.connect(self.db) as db:
            before = db.execute(
                "SELECT * FROM observations ORDER BY instant"
            ).fetchall()
            manifests = db.execute("SELECT * FROM batch_manifest").fetchall()
            active = db.execute("SELECT * FROM active_snapshot").fetchall()
            db.execute(
                "CREATE TRIGGER fail_insert BEFORE INSERT ON observations BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            run(replacement, self.db)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(
                db.execute("SELECT * FROM observations ORDER BY instant").fetchall(),
                before,
            )
            self.assertEqual(
                db.execute("SELECT * FROM batch_manifest").fetchall(), manifests
            )
            self.assertEqual(
                db.execute("SELECT * FROM active_snapshot").fetchall(), active
            )
            db.execute("DROP TRIGGER fail_insert")
        self.assertEqual(run(self.source, self.db), (original, True))
        recovered, cached = run(replacement, self.db)
        self.assertFalse(cached)
        self.assertEqual(recovered["accepted_rows"], 2)

    def test_fault_types(self):
        rows = [r.copy() for r in self.raw[:4]]
        rows[0]["hr"] = "25"
        rows[1]["cnt"] = "999999"
        rows[2]["hum"] = "NaN"
        rows.append(rows[3].copy())
        good, bad = validate(rows)
        self.assertEqual(len(good), 1)
        self.assertEqual(len(bad), 4)

    def test_bad_schema_preserves_snapshot(self):
        run(self.source, self.db)
        p = Path(self.tmp.name) / "bad.csv"
        p.write_text("x\n1\n")
        with self.assertRaises(ValueError):
            run(p, self.db)
        with sqlite3.connect(self.db) as d:
            self.assertEqual(
                d.execute("select count(*) from observations").fetchone()[0], 17379
            )

    def test_empty_batch_preserves_snapshot(self):
        run(self.source, self.db)
        p = Path(self.tmp.name) / "empty.csv"
        p.write_text(",".join(FIELDS) + "\n")
        with self.assertRaises(ValueError):
            run(p, self.db)

    def test_missing_database_returns_503_without_creating_file(self):
        missing = Path(self.tmp.name) / "missing.sqlite"
        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.database = missing
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health")
            self.assertEqual(error.exception.code, 503)
            self.assertFalse(missing.exists())
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_actual_http(self):
        run(self.source, self.db)
        s = HTTPServer(("127.0.0.1", 0), Handler)
        s.database = self.db
        t = threading.Thread(target=s.serve_forever, daemon=True)
        t.start()
        try:
            u = "http://127.0.0.1:" + str(s.server_port)
            with urllib.request.urlopen(u + "/health") as r:
                self.assertEqual(json.load(r)["rows"], 17379)
            with urllib.request.urlopen(
                u + "/daily?start=2011-01-01&end=2011-01-01"
            ) as r:
                self.assertEqual(len(json.load(r)["data"]), 1)
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(u + "/daily?start=invalid")
            self.assertEqual(c.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(u + "/missing")
            self.assertEqual(c.exception.code, 404)
        finally:
            s.shutdown()
            s.server_close()
            t.join()


if __name__ == "__main__":
    unittest.main()

"""Read-only localhost API. Run pipeline.py before starting."""

import argparse, json, sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import date
from pathlib import Path


def query(database, path):
    url = urlparse(path)
    with sqlite3.connect(
        Path(database).resolve().as_uri() + "?mode=ro", uri=True
    ) as db:
        if url.path == "/health":
            return 200, {
                "status": "ok",
                "rows": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            }
        if url.path == "/daily":
            params = parse_qs(url.query)
            try:
                start = date.fromisoformat(
                    params.get("start", ["2011-01-01"])[0]
                ).isoformat()
                end = date.fromisoformat(
                    params.get("end", ["2012-12-31"])[0]
                ).isoformat()
                if start > end:
                    raise ValueError()
            except ValueError:
                return 400, {"error": "Use ISO dates with start <= end"}
            rows = db.execute(
                "SELECT dteday,COUNT(*),SUM(cnt) FROM observations WHERE dteday BETWEEN ? AND ? GROUP BY dteday ORDER BY dteday",
                (start, end),
            ).fetchall()
            return 200, {
                "data": [
                    {"date": d, "observed_hours": n, "rentals": c} for d, n, c in rows
                ]
            }
        return 404, {"error": "Route not found"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            status, payload = query(self.server.database, self.path)
        except sqlite3.Error:
            status, payload = 503, {"error": "Database unavailable; run pipeline first"}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--database", default="mobility.sqlite")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--host", default="127.0.0.1")
    a = p.parse_args()
    s = HTTPServer((a.host, a.port), Handler)
    s.database = a.database
    print("API listening on", a.host, a.port, flush=True)
    s.serve_forever()

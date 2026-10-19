# Local operator guide

## Ingest
Run pipeline.py with --input, --database and --output paths. Preserve raw CSV and its SHA-256. Review accepted/rejected counts and reason codes before consuming aggregates. The clean source has missing hours; never assume 24 rows per day.

## Failure recovery
- Schema mismatch or empty valid set: existing data remain intact; inspect upstream format before retrying.
- SQLite lock: stop the competing writer and retry the same source. Do not delete the database to resolve a lock.
- JSON export failure: correct output permissions/path and rerun; the audit remains in batch_manifest.
- API 503: run the pipeline against the API's database path, then retry health.
- Unexpected results with a cached hash: rerun the known attributed input. Replay now compares all observation fields and transactionally reloads modified, missing, or extra observations. Investigate the cause; schema and audit metadata remain trusted, so arbitrary hostile edits require rebuilding from the known source.

## API contract
GET /health → 200 JSON {status, rows}; missing database tables → 503.
GET /daily?start=YYYY-MM-DD&end=YYYY-MM-DD → 200 JSON {data:[{date,observed_hours,rentals}]}; invalid/inverted dates → 400; no observations → empty data array.
Unknown routes → 404. SQL dates use placeholders; user text is never interpolated into SQL.

## Release check
Run tests, pipeline, evaluate, and compare output schema. Preserve environment versions and result files. Timing numbers depend on the local machine and are not service SLAs. A cloud adaptation needs authentication, managed storage, secret management, deployment testing, and budget approval.

## Container operations
From the repository root, run `docker compose up --build --wait`. Port 8080 is published only on 127.0.0.1. Use `docker compose logs` to inspect startup and request logs, and `docker compose down` to stop. If 8080 is occupied, stop that service or adjust the host side of the mapping. The image includes an immutable historical snapshot; it is not a live ingestion service. The API opens SQLite explicitly read-only and returns 503 without creating a database file when its snapshot is unavailable.

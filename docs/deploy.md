# Deploying

## Render (Blueprint)

`render.yaml` at the repository root defines the whole stack: Postgres 16 (Render enables
`pgvector` on `CREATE EXTENSION`), a Key Value store for Celery, the API (Docker), one
worker with embedded beat, and the Next.js web app. In a Render project choose
**New → Blueprint**, connect `gokulzerone/signalalpha`, and apply. The API's pre-deploy
command runs the migrations and the idempotent mock bootstrap, so the dashboard has data
on the first deploy. The web service gets the API's internal address and the generated
API key automatically; the key never reaches the browser.

Notes:
- Raw document bytes go to `/tmp/objects` on each instance (Render has no shared object
  store); the extracted text that the evidence viewer needs lives in Postgres, so nothing
  user-visible depends on it. Point `SIGNALALPHA_OBJECT_STORE_DIR` at a mounted disk or
  swap in an S3-compatible store when live ingestion is switched on.
- Plans in the file are the smallest paid ones because free web services sleep and the
  free Postgres expires; change them in the dashboard or the file.
- To use Claude instead of the offline template client, set
  `SIGNALALPHA_LLM_PROVIDER=anthropic` and add `ANTHROPIC_API_KEY` on the API and worker.

## Docker Compose

`docker compose -f infra/docker-compose.yml up` runs the same stack locally with MinIO.

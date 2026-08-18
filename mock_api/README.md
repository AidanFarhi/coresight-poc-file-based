# Fake Source Systems

Simulated third-party vendor APIs for the Coresight POC, hosted on Fly.io.

Deployed **separately** from the Coresight AWS stack (see
[`docs/project-overview.md`](../docs/project-overview.md) section 11) so the
ingestion task integrates over the public internet with an endpoint it does
not own, exactly as it would with a real vendor.

Currently a hello-world skeleton. The field-service and accounting routes
land on top of it.

## Layout

| File | Purpose |
| --- | --- |
| `app/main.py` | FastAPI application |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image Fly builds and runs |
| `fly.toml` | Fly app config (app name, region, port, health check, VM size) |

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- <http://127.0.0.1:8000/> — hello world
- <http://127.0.0.1:8000/health> — health check Fly polls
- <http://127.0.0.1:8000/docs> — auto-generated OpenAPI docs

## Deploy

One-time setup:

```bash
fly auth login                      # or: fly auth signup
fly apps create coresight-mock-api
```

If that name is taken, pick another and update `app` in `fly.toml` to match.

Then, from this directory:

```bash
fly deploy
```

Fly builds the Dockerfile on a remote builder (no local Docker needed) and
boots one machine. Verify:

```bash
curl https://coresight-mock-api.fly.dev/
fly status
fly logs
```

Every later change is the same single `fly deploy`.

## Cost and scaling notes

`fly.toml` sets `min_machines_running = 0` with `auto_stop_machines = 'stop'`,
so the machine suspends when idle and wakes on the next request — a weekly
batch pull costs nearly nothing, at the price of a cold start on the first
request. A `shared-cpu-1x` / 256MB VM is ample for serving static JSON.

## Note for when real data lands

The Docker build context is this directory, and the repo's `data/` directory
is both outside it and gitignored — the container has no path to the
developer's local files. When the endpoints start serving generated datasets,
decide deliberately how the data gets into the image: committed fixtures
under `mock_api/`, generated at build time, or generated at startup.

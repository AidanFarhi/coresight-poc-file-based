# Fake Source Systems

Simulated third-party vendor APIs for the Coresight POC, hosted on Fly.io.

Deployed **separately** from the Coresight AWS stack (see
[`docs/project-overview.md`](../docs/project-overview.md) section 11) so the
ingestion task integrates over the public internet with an endpoint it does
not own, exactly as it would with a real vendor.

Currently serves **hard-coded sample payloads** — the response shapes are
the real contract, the volume is not. No auth and no fault injection yet;
both are deliberate deferrals, not oversights (see Not built yet, below).

## Layout

| File | Purpose |
| --- | --- |
| `app/main.py` | FastAPI application, mounts both source routers |
| `app/field_service.py` | Source A — field service / CRM routes |
| `app/accounting.py` | Source B — accounting routes |
| `app/models.py` | Pydantic response schemas (the wire contract) |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container image Fly builds and runs |
| `fly.toml` | Fly app config (app name, region, port, health check, VM size) |

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- <http://127.0.0.1:8000/health> — health check Fly polls
- <http://127.0.0.1:8000/docs> — auto-generated OpenAPI docs, the readable
  version of every schema below

## Endpoints

Both sources return their whole dataset in one call — no pagination, per
[section 2](../docs/project-overview.md) of the overview.

**Source A — field service / CRM** (ServiceTitan-like). Bare JSON arrays,
no envelope:

| Endpoint | Returns |
| --- | --- |
| `GET /field-service/customers` | `[{customer_id, customer_name, created_at}]` |
| `GET /field-service/jobs` | `[{job_id, customer_id, job_type, status, scheduled_date, completed_date}]` |
| `GET /field-service/invoices` | `[{invoice_id, job_id, invoice_date, status, amount, updated_at}]` |

**Source B — accounting** (QuickBooks-like). Rows nested in a metadata
envelope, intentionally unlike Source A so the ingestion task cannot reuse
one adapter for both:

| Endpoint | Returns |
| --- | --- |
| `GET /accounting/expenses` | `{QueryResponse: {Expense: [...]}, time, maxResults}` |

```json
{
  "QueryResponse": {
    "Expense": [
      {
        "txn_id": "TXN-00001",
        "vendor_name": "Baker Distributing",
        "txn_date": "2025-01-07",
        "amount": 1282.03,
        "category": "material",
        "job_ref": "JOB-00005",
        "customer_ref": null,
        "memo": "material for JOB-00005",
        "status": "posted"
      }
    ]
  },
  "time": "2026-08-18T23:41:07+00:00",
  "maxResults": 1
}
```

Field names mirror the generated datasets in `data/` exactly, so swapping
samples for real files is a data change, not a schema change. The samples
cover the shape variations that matter: a canceled job, a null
`completed_date`, a void invoice, a null `job_id`, an expense matched by
`job_ref`, one matched only by `customer_ref`, and a negative adjustment.

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

## Not built yet

Deferred deliberately, in rough order of when the pipeline will need them:

- **Real data volume** — see the note below.
- **Authentication.** Section 2 calls both APIs authenticated, with
  credentials in Secrets Manager. Nothing checks a token today.
- **Fault injection.** Section 9 wants unavailable, auth-failure, and
  unexpected-schema responses on demand. Every endpoint is happy-path.

## Note for when real data lands

The Docker build context is this directory, and the repo's `data/` directory
is both outside it and gitignored — the container has no path to the
developer's local files. When the endpoints start serving generated datasets,
decide deliberately how the data gets into the image: committed fixtures
under `mock_api/`, generated at build time, or generated at startup.

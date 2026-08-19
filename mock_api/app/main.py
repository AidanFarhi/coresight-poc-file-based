"""Fake external source systems for the Coresight POC.

Stands in for the third-party vendors ABC Mechanical actually integrates
with, so the ingestion task talks to a real network endpoint it does not
own. Deployed separately from the Coresight AWS stack.

Both sources return their whole dataset in one call — no pagination, per
docs/project-overview.md section 2. Responses are hard-coded samples for
now: the shapes are real, the volume is not.
"""

from fastapi import FastAPI

from . import accounting, field_service

app = FastAPI(
    title="Coresight Mock Source APIs",
    description=(
        "Simulated third-party field-service and accounting APIs. "
        "Sample payloads only — no auth and no fault injection yet."
    ),
    version="0.2.0",
)

app.include_router(field_service.router)
app.include_router(accounting.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "hello world"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

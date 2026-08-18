"""Fake external source systems for the Coresight POC.

Stands in for the third-party vendors ABC Mechanical actually integrates
with, so the ingestion task talks to a real network endpoint it does not
own. Deployed separately from the Coresight AWS stack.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Coresight Fake Sources",
    description="Simulated third-party field-service and accounting APIs.",
    version="0.1.0",
)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "hello world"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

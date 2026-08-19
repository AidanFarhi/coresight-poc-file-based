"""Source A — field service / CRM API (ServiceTitan-like).

Returns bare JSON arrays: the full dataset in one call, no pagination and
no envelope. Sample records only for now; the shapes are the contract.
"""

from fastapi import APIRouter

from .models import Customer, Invoice, Job

router = APIRouter(prefix="/field-service", tags=["field-service"])

CUSTOMERS = [
    {
        "customer_id": "CUST-0001",
        "customer_name": "Evergreen Apartments LLC",
        "created_at": "2024-02-27",
    },
    {
        "customer_id": "CUST-0205",
        "customer_name": "Castillo Residence",
        "created_at": "2024-11-04",
    },
]

JOBS = [
    {
        "job_id": "JOB-00002",
        "customer_id": "CUST-0205",
        "job_type": "Install",
        "status": "completed",
        "scheduled_date": "2025-01-25",
        "completed_date": "2025-01-29",
    },
    {
        "job_id": "JOB-00007",
        "customer_id": "CUST-0001",
        "job_type": "Maintenance",
        "status": "canceled",
        "scheduled_date": "2025-02-03",
        "completed_date": None,
    },
]

INVOICES = [
    {
        "invoice_id": "INV-00001",
        "job_id": "JOB-00002",
        "invoice_date": "2025-01-29",
        "status": "posted",
        "amount": 912.74,
        "updated_at": "2025-01-29",
    },
    {
        "invoice_id": "INV-00002",
        "job_id": None,
        "invoice_date": "2025-02-04",
        "status": "void",
        "amount": 340.00,
        "updated_at": "2025-02-06",
    },
]


@router.get("/customers")
def list_customers() -> list[Customer]:
    return CUSTOMERS


@router.get("/jobs")
def list_jobs() -> list[Job]:
    return JOBS


@router.get("/invoices")
def list_invoices() -> list[Invoice]:
    return INVOICES

"""Source B — accounting API (QuickBooks-like).

Deliberately unlike Source A on the wire: rows arrive nested inside a
`QueryResponse` envelope alongside response metadata, so the ingestion task
needs a genuinely separate adapter rather than a reused one.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from .models import ExpenseResponse

router = APIRouter(prefix="/accounting", tags=["accounting"])

EXPENSES = [
    {
        "txn_id": "TXN-00001",
        "vendor_name": "Baker Distributing",
        "txn_date": "2025-01-07",
        "amount": 1282.03,
        "category": "material",
        "job_ref": "JOB-00005",
        "customer_ref": None,
        "memo": "material for JOB-00005",
        "status": "posted",
    },
    {
        "txn_id": "TXN-00010",
        "vendor_name": "Johnstone Supply",
        "txn_date": "2025-01-10",
        "amount": 1400.67,
        "category": "material",
        "job_ref": None,
        "customer_ref": "Castillo Residence",
        "memo": "material purchase - Castillo Residence",
        "status": "posted",
    },
    {
        "txn_id": "TXN-00044",
        "vendor_name": "Ferguson HVAC Supply",
        "txn_date": "2025-02-11",
        "amount": -85.50,
        "category": "adjustment",
        "job_ref": "JOB-00002",
        "customer_ref": None,
        "memo": "return credit - JOB-00002",
        "status": "posted",
    },
]


@router.get("/expenses")
def list_expenses() -> ExpenseResponse:
    return {
        "QueryResponse": {"Expense": EXPENSES},
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "maxResults": len(EXPENSES),
    }

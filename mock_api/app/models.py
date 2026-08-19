"""Response schemas for the two mock vendor APIs.

Field names mirror the generated datasets in `data/` exactly, so swapping
the hard-coded samples for the real files later is a data change, not a
schema change. The two vendors are deliberately unlike each other: see
docs/project-overview.md section 2.
"""

from pydantic import BaseModel


# --- Source A: field service / CRM (ServiceTitan-like) -------------------


class Customer(BaseModel):
    customer_id: str
    customer_name: str
    created_at: str


class Job(BaseModel):
    job_id: str
    customer_id: str
    job_type: str
    status: str
    scheduled_date: str
    completed_date: str | None


class Invoice(BaseModel):
    invoice_id: str
    job_id: str | None
    invoice_date: str
    status: str
    amount: float
    updated_at: str


# --- Source B: accounting (QuickBooks-like) ------------------------------


class Expense(BaseModel):
    txn_id: str
    vendor_name: str
    txn_date: str
    amount: float
    category: str
    job_ref: str | None
    customer_ref: str | None
    memo: str
    status: str


class ExpenseQuery(BaseModel):
    """The `QueryResponse` object an accounting vendor nests its rows in."""

    Expense: list[Expense]


class ExpenseResponse(BaseModel):
    """Accounting wraps its payload in metadata; field service does not."""

    QueryResponse: ExpenseQuery
    time: str
    maxResults: int

#!/usr/bin/env python3
"""Generate the baseline fake-source dataset for the Coresight file-based POC.

Writes, under --out-dir (default <repo>/data):
    field-service/customers.json
    field-service/jobs.json
    field-service/invoices.json
    accounting/expenses.json
    payroll/labor_<YYYYMMDD>.csv  (one full-history dump — see payroll_feed.py)
    defects_manifest.json         (record-level list of every defect seeded below)

Every source here is a full load. The field-service and accounting JSON files back
APIs that return their whole dataset on each call, and the payroll vendor publishes
its entire labor history as one dated CSV per batch. There is no per-week payroll
file and no incremental grain anywhere in this dataset.

The payroll drop directory is cleared first, so this script always leaves the
simulated SFTP server holding exactly one baseline dump.

Deterministic given the same --seed (pass --batch-date too if you also need the
dump filename to be stable). See docs/known_defects.md for what each defect
category is expected to do downstream — validation failure vs. business exception
vs. silently excluded.

Usage:
    python synthetic_data_generation/generate_base_data.py [--seed 42] [--months 8] [--out-dir data]
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

import payroll_feed

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = SCRIPT_DIR.parent / "data"
DEFAULT_START_DATE = date(2025, 1, 1)

# Curated commercial/institutional accounts: recurring service contracts (HOAs, property
# managers, schools, medical/retail plazas) that realistically generate many more jobs per
# customer than a one-off residential visit. See build_customers() for the weighting.
RECURRING_CUSTOMER_NAMES = [
    "Evergreen Apartments LLC", "Fairview Office Park", "Harbor Point Retail Center",
    "Ivy Lane Condos", "Kessler Manufacturing", "Lakeside Medical Plaza",
    "Northgate Business Center", "Parkview Elementary School", "Summit Ridge HOA",
    "Union Square Bakery", "Westbrook Storage Facility", "Yorkville Church",
    "Greenfield Auto Repair", "Maple Street Daycare", "Pine Hollow Apartments",
    "Sterling Law Offices", "Riverside Diner", "Cascade Property Management",
    "Oakhurst Senior Living", "Brightwater Logistics",
]

# Surnames used to procedurally generate a large pool of one-off residential customers.
RESIDENTIAL_SURNAMES = [
    "Alvarez", "Baker", "Chen", "Delgado", "Garcia", "Johnson", "Martinez", "O'Neil",
    "Quinn", "Thompson", "Vargas", "Xiong", "Zeller", "Anderson", "Bishop", "Cortez",
    "Dawson", "Ellis", "Fitzgerald", "Gallagher", "Hendricks", "Ibarra", "Jansen",
    "Kowalski", "Larsen", "Mercer", "Novak", "Osei", "Patterson", "Quintero", "Rivas",
    "Sanderson", "Tran", "Underwood", "Villanueva", "Whitfield", "Yamada", "Zajac",
    "Abernathy", "Blackwood", "Castillo", "Dunbar", "Eastman", "Ferreira", "Grange",
    "Holloway", "Isherwood", "Jacoby", "Kessler", "Leclair", "Monroe", "Nakamura",
    "Ortega", "Pruitt", "Radcliffe", "Sundberg", "Tolliver", "Ueda", "Vance",
    "Winslow", "Yancey", "Zamora", "Ashworth", "Brannigan", "Calloway", "Deveraux",
    "Emerson", "Farrow", "Guerrero", "Hutchins", "Ionescu", "Jernigan", "Kellerman",
]

RESIDENTIAL_CUSTOMER_SUFFIXES = ["Residence", "Household", "Family Home", "Home"]

JOB_TYPES = ["Install", "Repair", "Maintenance", "Inspection"]

VENDORS = [
    "Carrier Distributors", "Trane Supply Co", "Ferguson HVAC Supply",
    "Grainger Industrial", "Johnstone Supply", "Baker Distributing",
    "Home Depot Pro", "United Refrigeration",
]

JOB_STATUS_WEIGHTS = [
    ("completed", 78),
    ("canceled", 8),
    ("in_progress", 8),
    ("scheduled", 6),
]


def weighted_choice(rng, weighted_options):
    total = sum(w for _, w in weighted_options)
    pick = rng.uniform(0, total)
    upto = 0
    for value, weight in weighted_options:
        upto += weight
        if pick <= upto:
            return value
    return weighted_options[-1][0]


def add_month(d):
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, 1)


def monday_of(d):
    """Labor is logged against the week a job was scheduled in."""
    return d - timedelta(days=d.weekday())


def next_seq(records, id_field, prefix):
    if not records:
        return 1
    return max(int(r[id_field].split("-")[1]) for r in records if r[id_field] and r[id_field].startswith(prefix)) + 1


def build_customers(rng, residential_count=350):
    """Recurring commercial/institutional accounts come first, followed by a large pool
    of procedurally-generated one-off residential customers. Job assignment in
    build_jobs() weights the recurring accounts much more heavily, which is what
    actually produces realistic jobs-per-customer volume."""
    customers = []
    seq = 1
    for name in RECURRING_CUSTOMER_NAMES:
        customers.append({
            "customer_id": f"CUST-{seq:04d}",
            "customer_name": name,
            "created_at": (date(2024, 1, 1) + timedelta(days=rng.randint(0, 300))).isoformat(),
        })
        seq += 1

    # Enumerate every surname/suffix combo up front and shuffle, so residential_count is
    # never bounded by chance collisions retrying against a fixed-size pool. If more names
    # are requested than there are combos, cycle back through with a numeric disambiguator.
    combos = [f"{s} {suf}" for s in RESIDENTIAL_SURNAMES for suf in RESIDENTIAL_CUSTOMER_SUFFIXES]
    rng.shuffle(combos)
    for i in range(residential_count):
        base = combos[i % len(combos)]
        cycle = i // len(combos)
        name = base if cycle == 0 else f"{base} {cycle + 1}"
        customers.append({
            "customer_id": f"CUST-{seq:04d}",
            "customer_name": name,
            "created_at": (date(2024, 1, 1) + timedelta(days=rng.randint(0, 300))).isoformat(),
        })
        seq += 1
    return customers


def build_customer_weights(customers):
    """Recurring commercial accounts (the first RECURRING_CUSTOMER_NAMES entries) are
    ~10x more likely to generate a given job than a one-off residential customer."""
    recurring_count = len(RECURRING_CUSTOMER_NAMES)
    return [(c, 10 if i < recurring_count else 1) for i, c in enumerate(customers)]


def build_jobs(rng, customers, start_date, months):
    jobs = []
    job_seq = 1
    current = start_date
    customer_weights = build_customer_weights(customers)
    for _ in range(months):
        jobs_this_month = rng.randint(150, 250)
        for _ in range(jobs_this_month):
            customer = weighted_choice(rng, customer_weights)
            scheduled_day = current + timedelta(days=rng.randint(0, 27))
            status = weighted_choice(rng, JOB_STATUS_WEIGHTS)
            completed_date = None
            if status == "completed":
                completed_date = scheduled_day + timedelta(days=rng.randint(0, 5))
            jobs.append({
                "job_id": f"JOB-{job_seq:05d}",
                "customer_id": customer["customer_id"],
                "job_type": rng.choice(JOB_TYPES),
                "status": status,
                "scheduled_date": scheduled_day.isoformat(),
                "completed_date": completed_date.isoformat() if completed_date else None,
            })
            job_seq += 1
        current = add_month(current)
    return jobs


def build_invoices(rng, jobs):
    invoices = []
    inv_seq = 1
    for job in jobs:
        if job["status"] not in ("completed", "canceled"):
            continue
        if job["status"] == "canceled" and rng.random() > 0.3:
            continue  # most canceled jobs never got invoiced at all
        amount = round(rng.uniform(180, 6200), 2)
        invoice_date = job["completed_date"] or job["scheduled_date"]
        status = "void" if job["status"] == "canceled" else "posted"
        invoices.append({
            "invoice_id": f"INV-{inv_seq:05d}",
            "job_id": job["job_id"],
            "invoice_date": invoice_date,
            "status": status,
            "amount": amount,
            "updated_at": invoice_date,
        })
        inv_seq += 1
    return invoices


def build_expenses(rng, jobs, customers):
    expenses = []
    seq = 1
    customer_by_id = {c["customer_id"]: c for c in customers}
    # Organic expenses only attach to jobs that were actually worked, so the deliberate
    # "canceled job with costs" defect injected later stays the sole source of that pattern.
    eligible_jobs = [j for j in jobs if j["status"] in ("completed", "in_progress")]
    for job in eligible_jobs:
        if rng.random() > 0.55:
            continue
        for _ in range(rng.randint(1, 2)):
            vendor = rng.choice(VENDORS)
            amount = round(rng.uniform(20, 1500), 2)
            category = "material" if rng.random() < 0.85 else "adjustment"
            match_style = weighted_choice(rng, [("direct", 60), ("customer", 25), ("memo", 10), ("none", 5)])
            job_ref = None
            customer_ref = None
            if match_style == "direct":
                job_ref = job["job_id"]
                memo = f"{category} for {job_ref}"
            elif match_style == "customer":
                customer_ref = customer_by_id[job["customer_id"]]["customer_name"]
                memo = f"{category} purchase - {customer_ref}"
            elif match_style == "memo":
                job_number = job["job_id"].split("-")[1]
                memo = f"Job #{job_number} - {category} pickup"
            else:
                memo = "misc supply run"
            expenses.append({
                "txn_id": f"TXN-{seq:05d}",
                "vendor_name": vendor,
                "txn_date": job["scheduled_date"],
                "amount": amount,
                "category": category,
                "job_ref": job_ref,
                "customer_ref": customer_ref,
                "memo": memo,
                "status": "posted",
            })
            seq += 1
    return expenses


def build_payroll(rng, jobs):
    """The vendor's complete labor history as one flat row set. There are no per-week
    files — every batch republishes all of these rows, so the weekly grain survives
    only in work_date."""
    rows = []
    for job in jobs:
        if job["status"] not in ("completed", "in_progress"):
            continue
        monday = monday_of(date.fromisoformat(job["scheduled_date"]))
        for _ in range(rng.randint(1, 2)):
            employee_id, employee_name, rate = rng.choice(payroll_feed.EMPLOYEES)
            work_date = monday + timedelta(days=rng.randint(0, 4))
            rows.append({
                "employee_id": employee_id,
                "employee_name": employee_name,
                "job_code": job["job_id"],
                "work_date": work_date.isoformat(),
                "hours": round(rng.uniform(1.5, 9.0), 2),
                "hourly_rate": rate,
            })
    return rows


def inject_known_defects(rng, customers, jobs, invoices, expenses, labor_rows):
    """Mutates the generated dataset in place and returns a manifest describing
    exactly which records were altered and why. See docs/known_defects.md for the
    expected downstream validation/exception behavior of each defect type."""
    manifest = []
    touched_invoice_ids = set()

    # 1. Duplicate invoices: clone the record under a new invoice_id.
    posted = [inv for inv in invoices if inv["status"] == "posted"]
    dup_targets = rng.sample(posted, k=min(3, len(posted)))
    inv_seq = next_seq(invoices, "invoice_id", "INV")
    for inv in dup_targets:
        touched_invoice_ids.add(inv["invoice_id"])
        dup = dict(inv)
        dup["invoice_id"] = f"INV-{inv_seq:05d}"
        inv_seq += 1
        invoices.append(dup)
        manifest.append({
            "type": "duplicate_invoice", "source_system": "field_service",
            "record_id": dup["invoice_id"], "related_record_id": inv["invoice_id"],
            "job_id": inv["job_id"],
            "description": f"Duplicate of {inv['invoice_id']} for job {inv['job_id']}, same amount/date.",
        })

    # 2. Missing job IDs: null out the job linkage on a couple of otherwise-normal invoices.
    candidates = [inv for inv in posted if inv["invoice_id"] not in touched_invoice_ids]
    missing_targets = rng.sample(candidates, k=min(2, len(candidates)))
    for inv in missing_targets:
        touched_invoice_ids.add(inv["invoice_id"])
        manifest.append({
            "type": "missing_job_id", "source_system": "field_service",
            "record_id": inv["invoice_id"], "job_id": inv["job_id"],
            "description": "invoice.job_id set to null; cannot be tied to a job.",
        })
        inv["job_id"] = None

    # 3. Unknown job codes in payroll.
    unknown_targets = rng.sample(labor_rows, k=min(4, len(labor_rows)))
    touched_rows = set(id(row) for row in unknown_targets)
    for row in unknown_targets:
        original_job_id = row["job_code"]
        row["job_code"] = f"JOB-9{rng.randint(9000, 9999)}"
        manifest.append({
            "type": "unknown_job_code", "source_system": "payroll",
            "record_id": payroll_feed.record_id(row),
            "job_id": original_job_id,
            "description": f"job_code rewritten to {row['job_code']}, which does not exist in "
                           f"jobs.json (the row's real work was against {original_job_id}).",
        })

    # 4. Duplicate labor rows: append a verbatim copy inside the same full dump.
    remaining_rows = [r for r in labor_rows if id(r) not in touched_rows]
    dup_labor_targets = rng.sample(remaining_rows, k=min(4, len(remaining_rows)))
    for row in dup_labor_targets:
        labor_rows.append(dict(row))
        manifest.append({
            "type": "duplicate_labor_row", "source_system": "payroll",
            "record_id": payroll_feed.record_id(row),
            "description": "row duplicated verbatim inside the same full dump; only one copy "
                           "may contribute to labor cost.",
        })

    # 5. Canceled jobs that still carry labor/material costs.
    canceled_jobs = [j for j in jobs if j["status"] == "canceled"]
    flagged = rng.sample(canceled_jobs, k=min(3, len(canceled_jobs)))
    txn_seq = next_seq(expenses, "txn_id", "TXN")
    for job in flagged:
        expenses.append({
            "txn_id": f"TXN-{txn_seq:05d}",
            "vendor_name": rng.choice(VENDORS),
            "txn_date": job["scheduled_date"],
            "amount": round(rng.uniform(50, 800), 2),
            "category": "material",
            "job_ref": job["job_id"],
            "customer_ref": None,
            "memo": f"material for {job['job_id']} (canceled after work started)",
            "status": "posted",
        })
        txn_seq += 1
        monday = monday_of(date.fromisoformat(job["scheduled_date"]))
        employee_id, employee_name, rate = rng.choice(payroll_feed.EMPLOYEES)
        labor_rows.append({
            "employee_id": employee_id,
            "employee_name": employee_name,
            "job_code": job["job_id"],
            "work_date": (monday + timedelta(days=rng.randint(0, 4))).isoformat(),
            "hours": round(rng.uniform(1.5, 6.0), 2),
            "hourly_rate": rate,
        })
        manifest.append({
            "type": "canceled_job_with_costs", "source_system": "field_service",
            "record_id": job["job_id"],
            "description": "canceled job retains a material expense and a labor row; must stay visible and flagged, not excluded.",
        })

    # 6. Malformed/missing required fields.
    malformed_customer = rng.choice(customers)
    manifest.append({
        "type": "malformed_record", "source_system": "field_service",
        "record_id": malformed_customer["customer_id"],
        "description": "customer_name blanked out to simulate a malformed source record.",
    })
    malformed_customer["customer_name"] = ""

    malformed_expense = rng.choice(expenses)
    manifest.append({
        "type": "malformed_record", "source_system": "accounting",
        "record_id": malformed_expense["txn_id"],
        "description": "amount field set to a non-numeric string; fails structural validation.",
    })
    malformed_expense["amount"] = "N/A"

    # 7. Ambiguous expense-to-job matches: log the organically-generated customer_ref-only
    #    expenses so they're catalogued alongside the deliberately injected defects.
    for e in expenses:
        if e.get("customer_ref") and not e.get("job_ref"):
            manifest.append({
                "type": "ambiguous_expense_match", "source_system": "accounting",
                "record_id": e["txn_id"],
                "description": "resolvable only via customer_ref; may match more than one open job for that customer.",
            })

    return manifest


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--months", type=int, default=8)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--batch-date", type=date.fromisoformat, default=date.today(),
                        help="date stamped into the payroll dump filename (default: today)")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    customers = build_customers(rng)
    jobs = build_jobs(rng, customers, DEFAULT_START_DATE, args.months)
    invoices = build_invoices(rng, jobs)
    expenses = build_expenses(rng, jobs, customers)
    labor_rows = build_payroll(rng, jobs)

    manifest = inject_known_defects(rng, customers, jobs, invoices, expenses, labor_rows)

    write_json(args.out_dir / "field-service" / "customers.json", customers)
    write_json(args.out_dir / "field-service" / "jobs.json", jobs)
    write_json(args.out_dir / "field-service" / "invoices.json", invoices)
    write_json(args.out_dir / "accounting" / "expenses.json", expenses)
    write_json(args.out_dir / "defects_manifest.json", manifest)

    cleared = payroll_feed.clear_dumps(args.out_dir)
    dump_path = payroll_feed.write_dump(
        payroll_feed.next_dump_path(args.out_dir, args.batch_date), labor_rows)

    print(f"seed={args.seed} months={args.months} out_dir={args.out_dir}")
    print(f"customers={len(customers)} jobs={len(jobs)} invoices={len(invoices)} "
          f"expenses={len(expenses)} labor_rows={len(labor_rows)}")
    cleared_note = f" (cleared {len(cleared)} prior file(s))" if cleared else ""
    print(f"payroll full dump: payroll/{dump_path.name}{cleared_note}")
    print(f"defects seeded: {len(manifest)} (see defects_manifest.json)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Mutate an already-generated baseline dataset to simulate what changes between two
scheduled pipeline runs: corrected invoices, jobs advancing status, accounting cleaning
up an ambiguous match, and a late payroll correction file.

Run this against the output of generate_base_data.py, in place, any number of times —
each run appends a batch to corrections_log.json and applies a fresh set of changes so
the next full extract naturally reflects them (no CDC needed; see project-overview.md
section 5's full-load principle).

Usage:
    python fake_sources/data_gen/apply_corrections.py [--seed 7] [--data-dir fake_sources/data]
"""

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR.parent / "data"
PAYROLL_FIELDNAMES = ["employee_id", "employee_name", "job_code", "work_date", "hours", "hourly_rate"]


def load_json(path):
    with path.open() as f:
        return json.load(f)


def write_json(path, data):
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def week_label(d):
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def correct_invoices(rng, invoices, today):
    posted = [inv for inv in invoices if inv["status"] == "posted"]
    targets = rng.sample(posted, k=min(2, len(posted)))
    changes = []
    for inv in targets:
        old_amount = inv["amount"]
        pct = rng.uniform(-0.15, 0.15)
        inv["amount"] = round(old_amount * (1 + pct), 2)
        inv["updated_at"] = today.isoformat()
        changes.append({
            "type": "invoice_corrected", "source_system": "field_service",
            "record_id": inv["invoice_id"], "job_id": inv["job_id"],
            "description": f"amount revised from {old_amount} to {inv['amount']}",
        })
    return changes


def add_late_invoice(rng, jobs, invoices, today):
    invoiced_job_ids = {inv["job_id"] for inv in invoices if inv["job_id"]}
    candidates = [j for j in jobs if j["status"] == "completed" and j["job_id"] not in invoiced_job_ids]
    if not candidates:
        return []
    job = rng.choice(candidates)
    seq = max((int(i["invoice_id"].split("-")[1]) for i in invoices), default=0) + 1
    invoice = {
        "invoice_id": f"INV-{seq:05d}",
        "job_id": job["job_id"],
        "invoice_date": today.isoformat(),
        "status": "posted",
        "amount": round(rng.uniform(180, 6200), 2),
        "updated_at": today.isoformat(),
    }
    invoices.append(invoice)
    return [{
        "type": "late_invoice", "source_system": "field_service",
        "record_id": invoice["invoice_id"], "job_id": job["job_id"],
        "description": "invoice arrived for a job completed in an earlier run; did not exist on the previous extract",
    }]


def advance_job_statuses(rng, jobs, today):
    changes = []
    in_progress = [j for j in jobs if j["status"] == "in_progress"]
    for job in rng.sample(in_progress, k=min(2, len(in_progress))):
        job["status"] = "completed"
        job["completed_date"] = today.isoformat()
        changes.append({
            "type": "job_status_advanced", "source_system": "field_service",
            "record_id": job["job_id"],
            "description": "status moved from in_progress to completed",
        })
    scheduled = [j for j in jobs if j["status"] == "scheduled"]
    for job in rng.sample(scheduled, k=min(2, len(scheduled))):
        job["status"] = "in_progress"
        changes.append({
            "type": "job_status_advanced", "source_system": "field_service",
            "record_id": job["job_id"],
            "description": "status moved from scheduled to in_progress",
        })
    return changes


def resolve_ambiguous_expense(rng, jobs, expenses):
    ambiguous = [e for e in expenses if e.get("customer_ref") and not e.get("job_ref")]
    if not ambiguous:
        return []
    expense = rng.choice(ambiguous)
    customer_jobs = [j for j in jobs if j["customer_id"] and expense["customer_ref"]]
    # Resolve against any job for that customer name via jobs' customer_id -> customer lookup
    # is out of scope here (accounting only knows the name); pick any completed job as the
    # "corrected" coding accounting applied.
    completed = [j for j in jobs if j["status"] == "completed"]
    if not completed:
        return []
    job = rng.choice(completed)
    expense["job_ref"] = job["job_id"]
    return [{
        "type": "expense_match_resolved", "source_system": "accounting",
        "record_id": expense["txn_id"], "job_id": job["job_id"],
        "description": "accounting added a direct job_ref to a previously customer_ref-only expense",
    }]


def add_payroll_correction(rng, data_dir, today):
    payroll_dir = data_dir / "payroll"
    weekly_files = sorted(p for p in payroll_dir.glob("*.csv") if "correction" not in p.stem)
    if not weekly_files:
        return []
    target_file = rng.choice(weekly_files)
    with target_file.open() as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    row = dict(rng.choice(rows))
    old_hours = row["hours"]
    row["hours"] = round(float(old_hours) + rng.uniform(-1.5, 1.5), 2)
    correction_path = target_file.with_name(f"{target_file.stem}_correction_{today.isoformat()}.csv")
    with correction_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PAYROLL_FIELDNAMES)
        writer.writeheader()
        writer.writerow(row)
    return [{
        "type": "payroll_correction", "source_system": "payroll",
        "record_id": f"{target_file.stem}:{row['employee_id']}:{row['work_date']}",
        "description": f"hours corrected from {old_hours} to {row['hours']} via follow-up file {correction_path.name}",
    }]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    today = date.today()

    jobs_path = args.data_dir / "field-service" / "jobs.json"
    invoices_path = args.data_dir / "field-service" / "invoices.json"
    expenses_path = args.data_dir / "accounting" / "expenses.json"

    jobs = load_json(jobs_path)
    invoices = load_json(invoices_path)
    expenses = load_json(expenses_path)

    changes = []
    changes += correct_invoices(rng, invoices, today)
    changes += add_late_invoice(rng, jobs, invoices, today)
    changes += advance_job_statuses(rng, jobs, today)
    changes += resolve_ambiguous_expense(rng, jobs, expenses)
    changes += add_payroll_correction(rng, args.data_dir, today)

    write_json(jobs_path, jobs)
    write_json(invoices_path, invoices)
    write_json(expenses_path, expenses)

    log_path = args.data_dir / "corrections_log.json"
    log = load_json(log_path) if log_path.exists() else []
    log.append({
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "seed": args.seed,
        "changes": changes,
    })
    write_json(log_path, log)

    print(f"applied {len(changes)} corrections at {today.isoformat()} (seed={args.seed})")
    for change in changes:
        print(f"  - {change['type']}: {change['record_id']}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Mutate an already-generated baseline dataset to simulate one more batch: corrected
invoices, jobs advancing status, accounting cleaning up an ambiguous match, and the
payroll vendor publishing a fresh full dump.

Run this against the output of generate_base_data.py, in place, any number of times —
each run appends a batch to corrections_log.json and applies a fresh set of changes so
the next full extract naturally reflects them (no CDC needed; see project-overview.md
section 6's full-load principle).

Every source stays a full load. The field-service and accounting JSON files are edited
in place because their APIs return the whole dataset on each call. Payroll works the
same way, just visibly: this script reads the newest dump off the simulated SFTP
server, applies its changes to the complete row set, and writes a NEW dated dump
beside it. Earlier dumps are left untouched as vendor-side history, which is why a
payroll correction needs no special correction file — the fixed row is simply present
in the next dump the ingestion task picks up.

Usage:
    python synthetic_data_generation/apply_corrections.py [--seed 7] [--data-dir data]
"""

import argparse
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import payroll_feed

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR.parent / "data"


def load_json(path):
    with path.open() as f:
        return json.load(f)


def write_json(path, data):
    with path.open("w") as f:
        json.dump(data, f, indent=2)


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
    # Resolving against the right job for that customer name would need a customer_id
    # lookup accounting doesn't have (it only knows the name), so pick any completed job
    # as the "corrected" coding accounting applied.
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


def correct_payroll_hours(rng, labor_rows):
    """A full-load feed has no follow-up correction file: the vendor re-publishes
    everything with the fixed row already in it, and the ingestion task can't tell
    the difference between a corrected row and one that was always that way."""
    if not labor_rows:
        return []
    row = rng.choice(labor_rows)
    old_hours = row["hours"]
    row["hours"] = round(float(old_hours) + rng.uniform(-1.5, 1.5), 2)
    return [{
        "type": "payroll_correction", "source_system": "payroll",
        "record_id": payroll_feed.record_id(row),
        "job_id": row["job_code"],
        "description": f"hours corrected from {old_hours} to {row['hours']}; the fix arrives "
                       "in the next full dump, not a separate correction file",
    }]


def add_labor_for_advanced_jobs(rng, labor_rows, advanced_job_ids, today):
    """Jobs that moved forward this batch picked up new time. It enters the dump as an
    ordinary row — new labor and corrected labor are indistinguishable in a full load,
    which is exactly why the pipeline can re-read the whole file every run."""
    changes = []
    for job_id in advanced_job_ids:
        employee_id, employee_name, rate = rng.choice(payroll_feed.EMPLOYEES)
        row = {
            "employee_id": employee_id,
            "employee_name": employee_name,
            "job_code": job_id,
            "work_date": (today - timedelta(days=rng.randint(0, 6))).isoformat(),
            "hours": round(rng.uniform(1.5, 9.0), 2),
            "hourly_rate": rate,
        }
        labor_rows.append(row)
        changes.append({
            "type": "labor_added", "source_system": "payroll",
            "record_id": payroll_feed.record_id(row),
            "job_id": job_id,
            "description": "new labor logged against a job whose status advanced this batch",
        })
    return changes


def republish_payroll_dump(rng, data_dir, advanced_job_ids, batch_date):
    """Read the newest drop off the simulated SFTP server, apply this batch's payroll
    changes to the full row set, and write a new dated dump beside it."""
    latest = payroll_feed.latest_dump(data_dir)
    if latest is None:
        print(f"  ! no payroll dump found under {payroll_feed.dump_dir(data_dir)}; "
              "run generate_base_data.py first. Skipping payroll changes.")
        return [], None
    labor_rows = payroll_feed.read_dump(latest)
    changes = correct_payroll_hours(rng, labor_rows)
    changes += add_labor_for_advanced_jobs(rng, labor_rows, advanced_job_ids, batch_date)
    dump_path = payroll_feed.write_dump(
        payroll_feed.next_dump_path(data_dir, batch_date), labor_rows)
    return changes, dump_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--batch-date", type=date.fromisoformat, default=date.today(),
                        help="date this batch is published under, and stamped into the "
                             "payroll dump filename (default: today)")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    today = args.batch_date

    jobs_path = args.data_dir / "field-service" / "jobs.json"
    invoices_path = args.data_dir / "field-service" / "invoices.json"
    expenses_path = args.data_dir / "accounting" / "expenses.json"

    jobs = load_json(jobs_path)
    invoices = load_json(invoices_path)
    expenses = load_json(expenses_path)

    changes = []
    changes += correct_invoices(rng, invoices, today)
    changes += add_late_invoice(rng, jobs, invoices, today)
    status_changes = advance_job_statuses(rng, jobs, today)
    changes += status_changes
    changes += resolve_ambiguous_expense(rng, jobs, expenses)

    # Every entry advance_job_statuses() returns is keyed by job_id, so its record_ids
    # are exactly the jobs that moved this batch.
    advanced_job_ids = [c["record_id"] for c in status_changes]
    payroll_changes, dump_path = republish_payroll_dump(
        rng, args.data_dir, advanced_job_ids, today)
    changes += payroll_changes

    write_json(jobs_path, jobs)
    write_json(invoices_path, invoices)
    write_json(expenses_path, expenses)

    log_path = args.data_dir / "corrections_log.json"
    log = load_json(log_path) if log_path.exists() else []
    log.append({
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "batch_date": today.isoformat(),
        "seed": args.seed,
        "payroll_dump": dump_path.name if dump_path else None,
        "changes": changes,
    })
    write_json(log_path, log)

    print(f"applied {len(changes)} corrections at {today.isoformat()} (seed={args.seed})")
    for change in changes:
        print(f"  - {change['type']}: {change['record_id']}")
    if dump_path:
        print(f"payroll full dump published: payroll/{dump_path.name}")


if __name__ == "__main__":
    main()

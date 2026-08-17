"""Shared model of the simulated payroll/timekeeping vendor's SFTP drop directory.

The vendor is configured to publish a full-history report on a schedule, so each
batch lands as its own dated CSV containing every labor row the vendor knows about
— not a weekly delta. Prior drops stay on the server as history, which is what
lets a correction simply appear in the next dump instead of needing a separate
correction file (see docs/project-overview.md section 2, Source C).

The ingestion task's SFTP client mirrors latest_dump(): list the drop directory,
pick the newest file, GET it.

Both generator scripts import from here so the drop naming and newest-file rules
cannot drift apart between them.
"""

import csv

FIELDNAMES = ["employee_id", "employee_name", "job_code", "work_date", "hours", "hourly_rate"]

DUMP_PREFIX = "labor_"
DUMP_GLOB = f"{DUMP_PREFIX}*.csv"

EMPLOYEES = [
    ("EMP-01", "Marcus Reed", 32.00),
    ("EMP-02", "Dana Whitfield", 29.50),
    ("EMP-03", "Luis Ortega", 34.00),
    ("EMP-04", "Priya Nair", 31.00),
    ("EMP-05", "Chris Boyle", 27.50),
    ("EMP-06", "Angela Ford", 33.00),
    ("EMP-07", "Sam Delacroix", 28.00),
    ("EMP-08", "Nina Petrov", 30.50),
    ("EMP-09", "Tyrell Banks", 26.00),
    ("EMP-10", "Wendy Salazar", 32.50),
    ("EMP-11", "Derek Munoz", 29.00),
    ("EMP-12", "Kayla Simmons", 31.50),
    ("EMP-13", "Jamal Carter", 27.00),
    ("EMP-14", "Elena Rossi", 33.50),
    ("EMP-15", "Trevor Lang", 26.50),
    ("EMP-16", "Monica Reyes", 30.00),
    ("EMP-17", "Brian Kowalski", 34.50),
    ("EMP-18", "Sofia Alvarado", 28.50),
    ("EMP-19", "Grant Osei", 31.00),
    ("EMP-20", "Renee Dubois", 29.50),
    ("EMP-21", "Victor Chan", 32.00),
    ("EMP-22", "Paula Ibarra", 27.50),
    ("EMP-23", "Kevin Marsh", 33.00),
    ("EMP-24", "Aisha Bello", 30.50),
    ("EMP-25", "Todd Bergstrom", 26.00),
]


def dump_dir(data_dir):
    return data_dir / "payroll"


def record_id(row):
    """Payroll rows carry no vendor-assigned key, so identify them the way someone
    reconciling the CSV by hand would. Deliberately not unique: a duplicated row
    shares its original's id, which is the point of that defect."""
    return f"{row['employee_id']}:{row['job_code']}:{row['work_date']}"


def latest_dump(data_dir):
    """The newest drop on the simulated server, or None if it's empty. Dump names
    sort chronologically, so lexical order is chronological order."""
    dumps = sorted(dump_dir(data_dir).glob(DUMP_GLOB))
    return dumps[-1] if dumps else None


def read_dump(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def next_dump_path(data_dir, batch_date):
    """A real vendor never overwrites a drop it already delivered — a pipeline run
    may already have consumed it — so a second batch on the same day lands as
    labor_<date>_02.csv rather than clobbering the first."""
    directory = dump_dir(data_dir)
    stamp = batch_date.strftime("%Y%m%d")
    path = directory / f"{DUMP_PREFIX}{stamp}.csv"
    seq = 2
    while path.exists():
        path = directory / f"{DUMP_PREFIX}{stamp}_{seq:02d}.csv"
        seq += 1
    return path


def write_dump(path, rows):
    """Ordered by work date the way a timekeeping export would be. sorted() is
    stable, so verbatim duplicate rows stay adjacent in the order they were added."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r["work_date"], r["employee_id"], r["job_code"]))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(ordered)
    return path


def clear_dumps(data_dir):
    """Baseline generation starts the simulated server from empty. Sweeps every CSV
    in the drop directory, not just labor_*.csv, so a dataset left over from the
    old one-file-per-week layout doesn't linger alongside the full dumps."""
    directory = dump_dir(data_dir)
    if not directory.exists():
        return []
    removed = sorted(directory.glob("*.csv"))
    for path in removed:
        path.unlink()
    return removed

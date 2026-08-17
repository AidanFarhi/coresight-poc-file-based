# Known Defects Catalog

This catalog documents every data-quality defect deliberately seeded by the
generator scripts in `synthetic_data_generation/`, per
[`../../docs/project-overview.md`](../../docs/project-overview.md) sections 7 and 8
("create known defects... so the expected validation and exception results are
known before the pipeline runs").

Record-level detail (exact IDs) is not hard-coded here — it's written by the
scripts themselves on every run:

- `generate_base_data.py` writes `data/defects_manifest.json`.
- `apply_corrections.py` appends a batch to `data/corrections_log.json`.

Both are regenerated/appended deterministically (given `--seed`), so `git diff`
on those files is the fastest way to see exactly what changed and why.

## Every source is a full load

This matters for reading the tables below. All three sources deliver their
complete dataset every batch:

- **field_service / accounting** — the JSON files back APIs that return the whole
  dataset in one call (no pagination).
- **payroll** — the vendor is configured to publish a full-history report, so each
  batch lands as its own dated CSV (`data/payroll/labor_<YYYYMMDD>.csv`)
  containing every labor row it knows about. Earlier dumps stay on the simulated
  SFTP server as vendor-side history; the ingestion task lists the directory,
  picks the newest, and GETs it. See `payroll_feed.py`.

The practical consequence: **there is no such thing as a payroll "correction
file."** A corrected row is simply present, already fixed, in the next full dump.
The pipeline cannot distinguish a corrected row from one that was always that way,
which is exactly why it can safely re-read the whole file every run.

Payroll rows carry no vendor-assigned key, so the manifests identify them by the
composite `employee_id:job_code:work_date` — deliberately *not* unique, since a
duplicated row shares its original's ID.

## Seeded by `generate_base_data.py`

| Defect | Source system | Fields affected | Expected pipeline behavior |
|---|---|---|---|
| Duplicate invoices | field_service | `invoices[].invoice_id` | Reconciliation validation should detect two invoice records for the same job/amount/date; only one should contribute to revenue. |
| Missing job IDs | field_service | `invoices[].job_id = null` | Cannot be matched to a job → exception (`missing_job_id`), excluded from revenue, not guessed. |
| Unknown job codes | payroll | `job_code` (CSV) | `job_code` rewritten to a `JOB-9xxxx` code with no matching `job_id` → exception (`unknown_job_code`); hours excluded from any job's labor cost. The manifest's `job_id` field records the real job the row's work belonged to. |
| Duplicate labor rows | payroll | full row, duplicated within the same full dump | Reconciliation validation should catch the duplicate; only one row's hours should count toward labor cost. |
| Canceled jobs with costs | field_service / accounting / payroll | `jobs[].status = "canceled"` with an associated expense + labor row | Job must still appear in `job_profitability.csv`, flagged — not excluded — per business rule in section 7. |
| Malformed customer record | field_service | `customers[].customer_name = ""` | Structural validation should flag a required field as blank/missing. |
| Malformed expense amount | accounting | `expenses[].amount = "N/A"` | Structural validation should flag a numeric field that fails to parse — this is a **critical** failure per section 8 ("inability to parse required fields"). |
| Ambiguous expense-to-job matches | accounting | `expenses[].customer_ref` set, `job_ref` null | Resolvable only via `customer_ref`, which may match more than one open job for that customer → exception (`ambiguous_expense_match`) if not confidently resolvable. |

`generate_base_data.py` clears the payroll drop directory before writing, so it
always leaves the simulated SFTP server holding exactly one baseline dump. (The
sweep removes every CSV in that directory, which also clears datasets left over
from the retired one-file-per-week layout.)

## Seeded by `apply_corrections.py`

Run this after `generate_base_data.py` to simulate the gap between two scheduled
runs. Each invocation applies a new, independently random batch (pass `--seed`
for a reproducible batch, and `--batch-date` to control the date the batch is
published under). It edits the field-service/accounting JSON in place and
publishes a **new** payroll dump alongside the existing ones.

| Defect | Source system | What changes | Expected pipeline behavior |
|---|---|---|---|
| Invoice corrected after an earlier run | field_service | `invoices[].amount`, `updated_at` bumped | Next full extract should reflect the new amount; no duplicate business record should result from the correction (section 7). |
| Source records updated between runs | field_service | `jobs[].status` advances (`scheduled → in_progress → completed`) | Job's disposition in the next report should follow its new status without manual intervention. |
| Late-arriving invoice | field_service | new row appended to `invoices.json` for an already-completed job | Should be picked up on the next full run like any other record — this is why the pipeline re-extracts fully each time rather than relying on CDC. |
| Ambiguous match resolved | accounting | `expenses[].job_ref` populated on a previously `customer_ref`-only row | Confirms the exception path is temporary/correctable, not a permanent data-loss condition. |
| Payroll correction | payroll | an existing row's `hours` revised, carried into a new full dump | Transform logic must use the corrected hours without double-counting the original — which falls out for free, since the original row no longer exists anywhere in the dump the task reads. |
| New labor for advanced jobs | payroll | new rows appended for jobs whose status advanced this batch | Ordinary new rows. Corrected labor and new labor are indistinguishable in a full load; both are simply what the newest dump says. |

Because each batch republishes the complete row set, the newest dump is always
the single source of truth for payroll — reading any older dump reproduces
exactly what a run on that date would have seen, which is what makes a failed run
replayable without re-contacting the vendor.

## Explicitly out of scope for these scripts

These defects from section 9 belong to components that don't exist yet and
are called out here so they aren't forgotten, not because they're unimportant:

- **SFTP transport failure modes** (missing file, bad credentials, bad host key,
  connection timeout, malformed/empty CSV) — these are properties of the fake
  timekeeping SFTP server and the ECS task's SFTP client code
  ([`../../docs/project-overview.md`](../../docs/project-overview.md) section 2,
  Source C / section 12), not of the CSV contents these scripts produce.
  - Note that section 9's "corrected file delivered on a later run" **is** now
    covered here, by the payroll-correction row above — under a full-load feed
    that scenario is a data property, not a transport one.
- **One API response that returns an unexpected schema** — this belongs to the
  fake `field_service_api` / `accounting_api` apps (schema drift is a property
  of the API response shape, not of the underlying JSON files these scripts
  produce).

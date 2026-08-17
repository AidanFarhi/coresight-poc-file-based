# Known Defects Catalog

This catalog documents every data-quality defect deliberately seeded by the
generator scripts in this directory, per `docs/project-overview.md` sections 7
and 8 ("create known defects... so the expected validation and exception
results are known before the pipeline runs").

Record-level detail (exact IDs) is not hard-coded here — it's written by the
scripts themselves on every run:

- `generate_base_data.py` writes `fake_sources/data/defects_manifest.json`.
- `apply_corrections.py` appends a batch to `fake_sources/data/corrections_log.json`.
- `simulate_payroll_upload.py` appends a batch to `fake_sources/data/payroll_uploads_log.json`.

`generate_base_data.py` and `apply_corrections.py` are regenerated/appended
deterministically (given `--seed`); `simulate_payroll_upload.py` is invoked
per week/per scenario via `--week` and `--simulate-missed-upload` rather than
a seed. `git diff` on the JSON logs is the fastest way to see exactly what
changed and why.

## Seeded by `generate_base_data.py`

| Defect | Source system | Fields affected | Expected pipeline behavior |
|---|---|---|---|
| Duplicate invoices | field_service | `invoices[].invoice_id` | Reconciliation validation should detect two invoice records for the same job/amount/date; only one should contribute to revenue. |
| Missing job IDs | field_service | `invoices[].job_id = null` | Cannot be matched to a job → exception (`missing_job_id`), excluded from revenue, not guessed. |
| Unknown job codes | payroll | `job_code` (CSV) | `job_code` has no matching `job_id` → exception (`unknown_job_code`); hours excluded from any job's labor cost. |
| Duplicate labor rows | payroll | full row, duplicated within one weekly CSV | Reconciliation validation should catch the duplicate; only one row's hours should count toward labor cost. |
| Canceled jobs with costs | field_service / accounting / payroll | `jobs[].status = "canceled"` with an associated expense + labor row | Job must still appear in `job_profitability.csv`, flagged — not excluded — per business rule in section 6. |
| Malformed customer record | field_service | `customers[].customer_name = ""` | Structural validation should flag a required field as blank/missing. |
| Malformed expense amount | accounting | `expenses[].amount = "N/A"` | Structural validation should flag a numeric field that fails to parse — this is a **critical** failure per section 7 ("inability to parse required fields"). |
| Ambiguous expense-to-job matches | accounting | `expenses[].customer_ref` set, `job_ref` null | Resolvable only via `customer_ref`, which may match more than one open job for that customer → exception (`ambiguous_expense_match`) if not confidently resolvable. |

## Seeded by `apply_corrections.py`

Run this after `generate_base_data.py` to simulate the gap between two scheduled
runs. Each invocation applies a new, independently random batch (pass `--seed`
for a reproducible batch).

| Defect | Source system | What changes | Expected pipeline behavior |
|---|---|---|---|
| Invoice corrected after an earlier run | field_service | `invoices[].amount`, `updated_at` bumped | Next full extract should reflect the new amount; no duplicate business record should result from the correction (section 6). |
| Source records updated between runs | field_service | `jobs[].status` advances (`scheduled → in_progress → completed`) | Job's disposition in the next report should follow its new status without manual intervention. |
| Late-arriving invoice | field_service | new row appended to `invoices.json` for an already-completed job | Should be picked up on the next full run like any other record — this is why the pipeline re-extracts fully each time rather than relying on CDC. |
| Ambiguous match resolved | accounting | `expenses[].job_ref` populated on a previously `customer_ref`-only row | Confirms the exception path is temporary/correctable, not a permanent data-loss condition. |
| Payroll correction / follow-up file | payroll | new `*_correction_<date>.csv` file alongside an existing weekly file, single corrected row | Simulates a real payroll vendor's follow-up feed; transform logic must apply the corrected hours without double-counting the original row. |

## Seeded by `simulate_payroll_upload.py`

Models the weekly presigned-URL upload flow described in `docs/project-overview.md`
section 2 (Source C). Run per week, against the output of `generate_base_data.py`.

| Defect | Source system | What changes | Expected pipeline behavior |
|---|---|---|---|
| Missing payroll file for one scheduled run | payroll | `--simulate-missed-upload`: no file written to `payroll_inbound/<week>.csv` | Structural validation should flag the missing expected source file for that run; this is a **critical** failure per section 7. |

## Explicitly out of scope for these scripts

This defect from section 8 belongs to a component that doesn't exist yet and is
called out here so it isn't forgotten, not because it's unimportant:

- **One API response that returns an unexpected schema** — this belongs to the
  fake `field_service_api` / `accounting_api` apps (schema drift is a property
  of the API response shape, not of the underlying JSON files these scripts
  produce).

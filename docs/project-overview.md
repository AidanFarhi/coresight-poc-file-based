# Coresight Systems — POC 1: Job Profitability Reporting Automation

# Purpose

Build a simulated end-to-end Coresight client engagement for a growing field-service business using a deliberately simple, file-first AWS architecture. The objective is to prove that one painful recurring report can be automated reliably without introducing a database or broader data platform before the business needs one.

Core question  
Could I take a real client with this problem tomorrow and confidently move them from discovery → audit → implementation → stabilization → handoff using a low-cost, low-maintenance batch process?

# 1\. Simulated Client

ABC Mechanical is a fictional 50–75 employee HVAC/service contractor completing roughly 150–250 jobs per month.

Current process  
Operations produces a weekly job-profitability report every Monday.  
The report combines job and invoice information, employee labor hours, and material/vendor expenses.  
An operations manager manually exports data, cleans it in Excel, joins files with formulas/lookups, investigates discrepancies, and publishes the final report.  
The process takes approximately 5–8 hours each week.  
Common problems include inconsistent job identifiers, duplicate records, missing job assignments, late invoices, canceled jobs with costs, and transactions that cannot immediately be reconciled.

Desired outcome  
By Monday morning, the system should automatically produce a trustworthy job-profitability report plus a clear exception report. The operations manager should spend time reviewing exceptions and business decisions rather than assembling data.

# 2\. Simulated Source Systems

Source A — Field Service / CRM API  
Simulate a ServiceTitan-like system.  
Entities: customers, jobs, invoices.  
Access pattern: REST API.  
The fake API returns the full dataset in a single call (no pagination) — one request returns the complete list — and should include canceled jobs, revised records, and occasional duplicate or malformed source records.

Source B — Accounting API  
Simulate a QuickBooks-like accounting system.  
Entities: vendor expenses, material purchases, adjustments.  
Access pattern: REST API.  
The schema should intentionally differ from the field-service system. Some expenses should contain a direct job reference; others should require matching through customer/project references or memo text.

Source C — Payroll / Timekeeping File Feed  
Simulate a payroll/timekeeping vendor that produces a weekly CSV.  
Fields: employee\_id, employee\_name, job\_code, work\_date, hours, hourly\_rate.  
Access pattern: no payroll vendor API, SFTP server, or inbound email address. A scheduled Lambda generates a short-lived presigned S3 POST URL scoped to a static payroll landing-zone prefix and emails it to the operations manager via SES; the ops manager opens the link, selects the file — the filename itself is flexible, only the destination prefix is fixed — and uploads directly to S3, no AWS login, file never passes through application compute. This was chosen over AWS Transfer Family (SFTP) specifically to avoid its ~$216/month fixed per-protocol-hour cost, and over inbound email (SES receiving) to avoid owning/renewing a domain and MX/DKIM records just to receive one file a week.  
Multiple uploads to the landing zone in a given period are expected and fine (accidental re-uploads, a corrected version). Resolving that — picking the latest file by S3 modified time and archiving every file present in the landing zone at run time — is the ETL script's responsibility as part of its extract step, not a separate reconciliation process.  
A second, independent Lambda triggers on every upload to the landing zone, runs a quick structural check on just that file, and emails the ops manager immediate pass/fail feedback. This is an early-warning courtesy signal only — it does not gate the pipeline or do any latest/archive resolution; the ETL's own validation at run time remains the authoritative check before publish.  
Include missing job codes, incorrect week assignments, duplicate rows, and corrections in later files, plus an occasional week where the ops manager never uploads at all.

# 3\. Simple File-First AWS Architecture

EventBridge schedule  
↓  
ECS/Fargate batch task  
↓  
Full extract from all source systems  
↓  
Immutable S3 raw snapshot  
↓  
Transform \+ validate in the same batch task  
↓  
Write candidate outputs to S3  
↓  
If critical validations pass: publish final files  
↓  
Email summary \+ secure download links

Supporting services  
S3: static payroll landing-zone prefix, immutable raw snapshots, candidate outputs, published reports, validation results, run manifests, and a per-run archive of every file seen in the payroll landing zone.  
Lambda (upload-link): generates the weekly presigned S3 upload URL for the payroll landing zone (and renders the minimal upload-form page); fully decoupled from the ECS task's networking, so it does not need to sit in the private subnet.  
Lambda (upload-validation): triggers on every upload to the payroll landing zone, runs a quick structural check on that file, and emails the ops manager pass/fail feedback — advisory only, does not gate the pipeline or pick/archive files.  
CloudWatch: task logs, execution status, errors, and alarms.  
EventBridge: invokes the scheduled ECS/Fargate task and the weekly payroll upload-link Lambda.  
SES or equivalent delivery mechanism: sends the report summary and secure links to the end user, the weekly payroll upload-link email, and the upload-validation feedback email.

Architecture principle  
Use one deployable batch process with clearly separated code modules. Do not introduce Step Functions, RDS/Postgres, Airflow, Spark, Kafka, a lakehouse, or a warehouse unless a later client requirement actually earns that complexity.

# 4\. S3 Layout and Run Auditability

Every run should get its own immutable run ID/prefix so a failure can be inspected without re-extracting the source systems.

Example layout  
payroll-inbound/landing/\*.csv         (static landing zone; ops manager uploads here via presigned URL; filename flexible)  
runs/\<run\_id\>/raw/jobs.json  
runs/\<run\_id\>/raw/invoices.json  
runs/\<run\_id\>/raw/expenses.json  
runs/\<run\_id\>/raw/labor.csv          (the latest landing-zone file as of this run, selected by the ETL)  
runs/\<run\_id\>/payroll-archive/\*.csv  (every file present in the landing zone at run time, including non-selected duplicates)  
runs/\<run\_id\>/candidate/job\_profitability.csv  
runs/\<run\_id\>/candidate/exceptions.csv  
runs/\<run\_id\>/metadata/validation\_results.json  
runs/\<run\_id\>/metadata/run\_manifest.json

Published layout  
published/current/job\_profitability.csv  
published/current/exceptions.csv  
published/current/summary.json

Run manifest  
Store run\_id, started\_at, completed\_at, status, source row counts, output row counts, exception count, validation status, raw S3 prefix, published flag, and error details if applicable.

Retention principle  
Raw snapshots are retained long enough to support debugging and auditability. Published outputs remain versioned by run. A failed run must never overwrite the last known-good published report.

# 5\. Batch Task Structure

Keep the code modular internally without turning each module into a separate AWS service.

Suggested modules  
extract/  
transform/  
validate/  
publish/  
notify/

Execution flow  
Create run ID and run prefix.  
Extract the full required dataset from the field-service API.  
Extract the full required dataset from the accounting API.  
Resolve the payroll file: list the static landing-zone prefix, select the file with the latest S3 modified time as the authoritative source for this run, and archive every file present in the landing zone (including non-selected duplicates) under the run's prefix.  
Persist each source exactly as received into the run's raw S3 prefix.  
Load the raw files into memory/dataframes or local task storage.  
Normalize, join, reconcile, and calculate the job-profitability dataset.  
Create business exceptions for records that cannot be safely reconciled.  
Run structural, reconciliation, and business-rule validations.  
Write candidate outputs and validation results to the run prefix.  
If critical validations fail, stop publication and alert.  
If validations pass, promote/copy the candidate outputs to the published/current location.  
Send the weekly delivery email.  
Write final run status to the manifest and emit logs/metrics.

Full-load principle  
Each scheduled run re-extracts the full relevant dataset from each source system. No CDC, watermark, incremental MERGE, or historical change-capture logic is required for the POC. Source corrections should naturally be reflected on the next successful full run.

# 6\. Business Rules to Simulate

Revenue comes from posted/eligible invoices, excluding canceled or voided invoices.  
Labor cost equals approved labor hours multiplied by the applicable simulated labor cost rate.  
Material/vendor transactions should be assigned to jobs when a trustworthy match exists.  
Canceled jobs with costs should remain visible and be flagged.  
Source corrections should alter the next generated report without creating duplicate business records.  
A record that cannot be confidently matched should appear in the exception output rather than being guessed or discarded.  
Gross profit \= revenue − labor cost − material cost − other cost.  
Gross margin \= gross profit / revenue when revenue is non-zero.

# 7\. Data Quality and Validation

Create known defects in the generated source data so the expected validation and exception results are known before the pipeline runs.

Structural validations  
Each expected source file/extract is present.  
Required columns/fields exist.  
Required identifiers are not unexpectedly null.  
Dates and numeric fields parse successfully.  
Each source returned a non-zero or otherwise plausible row count.  
Expected source/business keys are unique where required.

Reconciliation validations  
Extracted row counts equal the rows processed or explicitly excluded.  
Invoice totals reconcile from source extract to eligible/reportable totals according to documented rules.  
Every labor and expense record has a disposition: matched, intentionally excluded, or exception.  
No record silently disappears during transformation.  
Generated output row counts are within documented sanity bounds.

Business-rule validations  
Final output has one row per intended job grain.  
Gross-profit arithmetic is internally consistent.  
Gross-margin calculation is internally consistent.  
Canceled/voided records follow the documented inclusion rules.  
Unknown labor job codes become exceptions.  
Ambiguous expense-to-job matches become exceptions.  
Clearly impossible values, such as negative hours when not allowed by the source rules, are surfaced.

Validation severity  
Critical validation failures block publication. Examples: missing source extract, schema break, inability to parse required fields, reconciliation totals that do not balance, or corrupt/empty final output.  
Warnings/business exceptions do not necessarily block publication. Examples: unmatched expenses, unknown job codes, or canceled jobs with costs that require human review.

Validation output  
Write validation\_results.json containing check name, severity, PASS/FAIL/WARN status, message, and relevant record count.  
Write exceptions.csv containing exception\_type, source\_system, source\_record\_id, job\_id when known, description, and any fields needed for manual review.

# 8\. Simulated Defects

Duplicate invoices.  
Duplicate labor rows.  
Missing job IDs.  
Unknown job codes.  
Expenses with ambiguous job references.  
Canceled jobs containing labor/material costs.  
Invoices corrected after an earlier run.  
Source records updated between runs.  
Malformed or missing required fields.  
A missing payroll file for one scheduled run.  
One API response that returns an unexpected schema.

# 9\. End-User Delivery

The simulated operations manager should not need AWS access.

Primary delivery  
Send a scheduled Monday email with a short summary of the week's report.  
Include revenue, gross profit, gross margin, jobs below a margin threshold, and exception count.  
Provide secure time-limited download links to the published job\_profitability.csv and exceptions.csv files.

Optional POC extension  
Generate an XLSX workbook instead of or in addition to CSV if that better matches the simulated client's existing workflow.

# 10\. Fake Source-System Implementation

Fake field-service API  
Small Python service or mocked HTTP API.  
Generate 6–12 months of customers, jobs, and invoices.  
Return the full dataset in a single call — no pagination.  
Allow later source corrections between scheduled runs.

Fake accounting API  
Use a separate endpoint/schema from the field-service API.  
Generate vendor/material expenses with direct, indirect, ambiguous, and missing job references.

Payroll generator  
Python script that creates one weekly CSV at a time, matching the fields/format the real presigned-URL upload flow expects.  
The presigned-URL upload mechanism itself (upload-link Lambda, static landing zone, upload-validation Lambda) is real AWS infrastructure, not locally simulated — see section 2, Source C.  
Create occasional corrected replacement or follow-up records.

Data volume  
Keep volume modest: thousands to low hundreds of thousands of rows are enough. The purpose is workflow realism, correctness, recoverability, and business value—not scale benchmarking.

# 11\. Client-Facing Audit Simulation

Before building the pipeline, write a short simulated Data Workflow Audit as if ABC Mechanical were a real client.

The audit should capture  
Current reporting process.  
Business owner and consumers of the report.  
Estimated manual effort.  
Systems and fields required.  
Source-access method for each system.  
Ability to perform a full extract from each source.  
Data-quality concerns.  
Cross-system identifiers/matching strategy.  
Security/access considerations.  
Business rules and ambiguities requiring client confirmation.  
Expected file format and delivery method.  
Proposed AWS architecture.  
Scope exclusions.  
Expected value.  
Implementation estimate.  
Go / conditional-go / no-go recommendation.

Important  
Distinguish simulated client facts from assumptions invented for the POC. The audit should explicitly determine whether a simple full-refresh file-first pattern is sufficient or whether the client's requirements justify a database-backed pattern.

# 12\. Implementation Deliverables

Infrastructure  
New isolated AWS sandbox account.  
Infrastructure-as-code for the required AWS resources where practical.  
S3 buckets/prefixes and lifecycle configuration.  
ECS/Fargate task definition and container image.  
Lambda + minimal upload-form page (API Gateway) for the weekly payroll presigned-URL upload.  
Lambda for post-upload payroll file validation and ops-manager notification.  
EventBridge schedule(s).  
CloudWatch logging and basic alarms.  
SES or equivalent delivery configuration.

Application / data code  
Fake-source generators/APIs.  
Full API extraction code.  
Payroll CSV handling.  
Presigned-URL generation logic for the weekly payroll upload.  
Latest-file resolution and archive logic for the payroll landing zone (part of the extract step).  
Raw S3 snapshot writer.  
Transformation/reconciliation code.  
Data-quality validators.  
Business-exception logic.  
Report generation.  
Publish/promote logic.  
Email/notification logic.

Documentation  
Architecture diagram.  
README with local/cloud setup.  
Source-to-output field mapping.  
Business-rule documentation.  
Validation catalog.  
Runbook.  
Failure/recovery procedures.  
Security/credential notes.  
Simulated client handoff guide.

# 13\. Definition of Done

A fresh AWS environment can be provisioned from documented steps.  
The workflow runs automatically from EventBridge.  
Each run performs a full extraction of the required source data.  
Every run preserves immutable raw source snapshots in S3.  
The process can be rerun safely without corrupting the currently published report.  
Known source defects produce the expected validation failures or business exceptions.  
Critical validation failures prevent publication.  
Warnings/exceptions are clearly surfaced without unnecessarily killing an otherwise trustworthy run.  
The generated job-profitability report calculates revenue, labor cost, material cost, gross profit, and gross margin correctly according to documented rules.  
A failed execution can be investigated from the S3 run snapshot and CloudWatch logs without re-extracting the source systems.  
The last known-good published output remains available if a run fails.  
The end user receives a simple email summary and secure access to the report and exceptions.  
Another engineer could understand the architecture, business rules, and operating procedure from the documentation.

# 14\. Deliberate Non-Goals

No Postgres/RDS.  
No warehouse.  
No generalized data platform.  
No incremental/CDC pipeline.  
No Step Functions.  
No real-time streaming.  
No Spark.  
No lakehouse.  
No Kafka.  
No Kubernetes.  
No machine learning.  
No AI agent.  
No custom client portal.  
No elaborate BI platform.  
No attempt to simulate enterprise-scale data volumes.

# 15\. Suggested Build Order

Phase 1 — Generate realistic fake data and manually calculate the expected profitability result for a small test subset.  
Phase 2 — Build the fake field-service API, fake accounting API, and payroll-file generator.  
Phase 3 — Provision S3, ECS/Fargate, EventBridge, and CloudWatch.  
Phase 4 — Build the full-extraction logic and write immutable raw snapshots to S3.  
Phase 5 — Build the transform/reconciliation logic locally against raw snapshots.  
Phase 6 — Add validation checks and business-exception generation.  
Phase 7 — Generate candidate report files and implement safe publish/promotion behavior.  
Phase 8 — Add scheduled execution through EventBridge.  
Phase 9 — Add logging, alarms, and failure/recovery behavior.  
Phase 10 — Add email delivery and secure download links.  
Phase 11 — Run failure/recovery tests and intentionally inject source corrections/schema defects.  
Phase 12 — Produce the simulated Audit, runbook, and client handoff documentation.  
Phase 13 — Review the project as a Coresight engagement: what was difficult, what should the Audit have discovered earlier, what could be standardized, and what should remain client-specific?

Success criterion  
The project is successful if it demonstrates that one recurring manual reporting process can be converted into a small, understandable, low-cost AWS batch workflow that reliably produces trustworthy files, preserves an auditable copy of every source extract, clearly surfaces exceptions, and requires very little operational care.  

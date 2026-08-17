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

Source A — Field Service / CRM REST API  
Simulate a ServiceTitan-like system.  
Entities: customers, jobs, invoices.  
Access pattern: REST API over HTTPS, authenticated. Returns the full dataset in a single call — no pagination, a deliberate simplification decision — and should include canceled jobs, revised records, occasional duplicate or malformed source records, and realistic failure modes (unavailable, authentication failure, unexpected schema).

Source B — Accounting REST API  
Simulate a QuickBooks-like accounting system.  
Entities: vendor expenses, material purchases, adjustments.  
Access pattern: REST API over HTTPS, authenticated, full extract in a single call (no pagination, consistent with Source A).  
The schema should intentionally differ from the field-service system. Some expenses should contain a direct job reference; others should require matching through customer/project references or memo text. Include realistic failure modes (unavailable, authentication failure, unexpected schema).

Source C — Timekeeping / Payroll SFTP Feed  
Simulate an external payroll/timekeeping vendor that automatically produces a weekly CSV and makes it available on its own SFTP server — Coresight pulls it. No human export or upload exists in the normal flow.  
Fields: employee\_id, employee\_name, job\_code, work\_date, hours, hourly\_rate.  
Access pattern: the ECS/Fargate task connects outbound to the vendor's SFTP server (TCP/22) during its scheduled run and performs an SFTP GET for that week's file. Host key and credentials are checked against values stored in Secrets Manager; verification must remain enabled and is never bypassed for convenience.  
Include missing job codes, incorrect week assignments, duplicate rows, and corrections in later files, plus realistic connection failure modes: missing file, bad credentials, bad host key, connection timeout, malformed CSV, empty CSV.

# 3\. Core Architecture

EventBridge schedule  
↓  
ECS/Fargate batch task launches in the explicit Coresight VPC's public subnet, receiving a temporary public IP  
↓  
Outbound-only connections to: Field Service/CRM API (HTTPS), Accounting API (HTTPS), external timekeeping SFTP server (TCP/22), and required AWS service APIs  
↓  
Immutable S3 raw snapshot  
↓  
Transform \+ validate in the same batch task  
↓  
Write candidate outputs to S3  
↓  
If critical validations pass: publish final files  
↓  
Deliver via the configured delivery adapter (email \+ secure download links for POC 1)  
↓  
Task stops — no persistent compute or NAT infrastructure remains running between runs

Supporting services  
S3: immutable raw snapshots, candidate outputs, published reports, validation results, and run manifests.  
Secrets Manager: CRM/Accounting API credentials and SFTP credentials/host-key material.  
CloudWatch: task logs, execution status, errors, and alarms.  
EventBridge: invokes the scheduled ECS/Fargate task.  
SES or equivalent delivery mechanism: sends the report summary and secure links to the end user (see section 10, Delivery Abstraction).

Architecture principle  
Use one deployable batch process with clearly separated code modules. Do not introduce Step Functions, RDS/Postgres, Airflow, Spark, Kafka, a lakehouse, or a warehouse unless a later client requirement actually earns that complexity.

There is still no Postgres/RDS, no data warehouse, no Step Functions, no Airflow, no Spark, no Kafka, no lakehouse, no manual upload workflow, and no NAT Gateway by default.

# 4\. Networking Architecture

Default POC networking model  
Use an explicitly created VPC with a public subnet and short-lived ECS/Fargate tasks assigned public IPs, with zero inbound security-group rules. Do NOT use private subnets or a NAT Gateway as the default POC architecture.

Rationale  
This workload is an outbound-only, short-lived batch worker. It does not expose a web application or accept inbound traffic. A NAT Gateway adds persistent hourly and data-processing cost even when the weekly job isn't running, and that cost is difficult to justify for a small recurring reporting workflow unless a real client requirement earns it.

## Explicit VPC

Do not rely on the AWS account's default VPC. Provision a dedicated VPC explicitly for the POC. The reason is repeatability and isolation: infrastructure should be reproducible through Terraform, networking assumptions should be explicit, the deployment should not depend on whatever happens to exist in a client's account, routing/security behavior should be documented, and the same pattern should be portable to another AWS account.

Keep the VPC minimal. Expected resources:  
Dedicated VPC.  
One or more public subnets, only as needed.  
Internet Gateway.  
Public route table with a route to the Internet Gateway.  
ECS/Fargate task security group with zero inbound rules.

Do not add networking components that are not required.

## Security Model

The ECS task may receive a public IP, but it must not accept inbound traffic.

> A public IP does not mean the workload is publicly accessible. The task security group has no inbound rules, and the workload exists only to make outbound connections during a short-lived batch execution.

Security requirements:  
Task security group has zero inbound rules.  
No SSH access.  
No exposed application ports.  
Outbound access only for required integrations.  
HTTPS/TLS verification must remain enabled.  
SFTP host-key verification must remain enabled.  
Credentials stored in Secrets Manager.  
ECS task role follows least privilege.  
No credentials baked into container images.  
No long-lived AWS access keys.  
CloudWatch logs enabled.  
S3 access scoped to the required buckets/prefixes.  
Secrets access scoped to the required secrets.

Do not disable security checks for convenience.

## NAT Gateway Escalation Pattern (Optional)

Document private subnet \+ NAT Gateway as an OPTIONAL escalation pattern rather than part of POC 1. Use it when a real requirement exists, such as:  
Vendor requires source-IP allowlisting.  
Client requires private workloads by policy.  
Fixed egress IP is required.  
Compliance/security architecture requires controlled, centralized egress.  
Workload eventually requires networking patterns that make public-IP tasks inappropriate.

Conceptually: Private Fargate → NAT Gateway → Elastic IP / controlled egress → external vendor.

> Do not introduce a NAT Gateway merely because it looks more enterprise-grade.

The default Coresight design principle:

> Use the minimum architecture that satisfies the actual security and operational requirements.

## Cost Philosophy

A NAT Gateway creates ongoing hourly and data-processing cost even when the weekly ETL job is not running. For small service businesses, infrastructure cost should be proportional to the actual value/workload.

The public-subnet Fargate model allows:  
EventBridge invokes the task.  
Fargate runs only when needed.  
The task gets outbound internet access.  
The task stops.  
No always-on NAT Gateway exists.

This is intentionally optimized for low idle cost, low operational complexity, easy handoff, easy debugging, repeatability, and sufficient security for an outbound-only batch workload. This model is not claimed to be universally appropriate — a different client, compliance posture, or workload shape could change the calculus, and that tradeoff should be documented honestly rather than asserted as one-size-fits-all.

# 5\. S3 Layout and Run Auditability

Every run should get its own immutable run ID/prefix so a failure can be inspected without re-extracting the source systems.

Example layout  
runs/\<run\_id\>/raw/jobs.json  
runs/\<run\_id\>/raw/invoices.json  
runs/\<run\_id\>/raw/expenses.json  
runs/\<run\_id\>/raw/labor.csv  
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

# 6\. Batch Task Structure

Keep one deployable batch application. Do not decompose the pipeline into many AWS services.

Suggested internal code boundaries  
extract/  
&nbsp;&nbsp;crm.py  
&nbsp;&nbsp;accounting.py  
&nbsp;&nbsp;sftp.py  
transform/  
validate/  
publish/  
notify/

Execution flow  
1\. Create run ID and run prefix.  
2\. Retrieve required Secrets Manager secrets.  
3\. Extract CRM data.  
4\. Extract Accounting data.  
5\. Pull the timekeeping SFTP labor file.  
6\. Write exact source artifacts to S3 raw.  
7\. Transform/reconcile: normalize, join, reconcile, and calculate the job-profitability dataset.  
8\. Generate business exceptions for records that cannot be safely reconciled.  
9\. Run structural, reconciliation, and business-rule validations.  
10\. Write candidate outputs to the run prefix.  
11\. Persist validation results and the run manifest.  
12\. Block publication on critical failures.  
13\. Safely promote valid output to the published/current location.  
14\. Deliver/report the result via the configured delivery adapter.  
15\. Emit logs/metrics.

Full-load principle  
Each scheduled run re-extracts the full relevant dataset from each source system. No CDC, watermark, incremental MERGE, or historical change-capture logic is required for the POC. Source corrections should naturally be reflected on the next successful full run.

# 7\. Business Rules to Simulate

Revenue comes from posted/eligible invoices, excluding canceled or voided invoices.  
Labor cost equals approved labor hours multiplied by the applicable simulated labor cost rate.  
Material/vendor transactions should be assigned to jobs when a trustworthy match exists.  
Canceled jobs with costs should remain visible and be flagged.  
Source corrections should alter the next generated report without creating duplicate business records.  
A record that cannot be confidently matched should appear in the exception output rather than being guessed or discarded.  
Gross profit \= revenue − labor cost − material cost − other cost.  
Gross margin \= gross profit / revenue when revenue is non-zero.

# 8\. Data Quality and Validation

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
Critical validation failures block publication. Examples: missing source extract, source API or SFTP unavailable, authentication failure, SFTP host-key verification failure, schema break, inability to parse required fields, reconciliation totals that do not balance, or corrupt/empty final output.  
Warnings/business exceptions do not necessarily block publication. Examples: unmatched expenses, unknown job codes, or canceled jobs with costs that require human review.

Validation output  
Write validation\_results.json containing check name, severity, PASS/FAIL/WARN status, message, and relevant record count.  
Write exceptions.csv containing exception\_type, source\_system, source\_record\_id, job\_id when known, description, and any fields needed for manual review.

# 9\. Simulated Defects

Duplicate invoices.  
Duplicate labor rows.  
Missing job IDs.  
Unknown job codes.  
Expenses with ambiguous job references.  
Canceled jobs containing labor/material costs.  
Invoices corrected after an earlier run.  
Source records updated between runs.  
Malformed or missing required fields.  
One API response that returns an unexpected schema.  
SFTP: missing file for one scheduled run.  
SFTP: bad credentials.  
SFTP: bad host key.  
SFTP: connection timeout.  
SFTP: malformed or empty CSV.  
SFTP: corrected file delivered on a later run.

# 10\. Delivery Abstraction and End-User Delivery

Do not define email as the core product.

Validated output → delivery adapter

Examples: email \+ secure S3 download links, CSV/XLSX delivery, SharePoint/Drive delivery, dashboard/BI integration, database/warehouse in a future architecture, API/other client integration.

For POC 1, email/secure file access remains the demonstrated delivery method.

The simulated operations manager should not need AWS access.

Primary delivery  
Send a scheduled Monday email with a short summary of the week's report.  
Include revenue, gross profit, gross margin, jobs below a margin threshold, and exception count.  
Provide secure time-limited download links to the published job\_profitability.csv and exceptions.csv files.

Optional POC extension  
Generate an XLSX workbook instead of or in addition to CSV if that better matches the simulated client's existing workflow.

# 11\. Simulated External Systems

Keep fake vendor infrastructure separate from the primary Coresight infrastructure. The Coresight Terraform stack should provision only the Coresight workload (VPC, ECS/Fargate, S3, IAM, Secrets Manager, EventBridge, CloudWatch). The fake CRM API, fake Accounting API, and fake SFTP server should exist separately, so the ETL behaves as though it is integrating with real external third-party vendors. Do not couple source-server resources into the main POC deployment.

# 12\. Fake Source-System Implementation

Fake field-service API  
Small Python service or mocked HTTP API.  
Generate 6–12 months of customers, jobs, and invoices.  
Return the full dataset in a single call — no pagination.  
Allow later source corrections between scheduled runs.

Fake accounting API  
Use a separate endpoint/schema from the field-service API.  
Generate vendor/material expenses with direct, indirect, ambiguous, and missing job references.

Fake timekeeping SFTP server  
Separately provisioned SFTP endpoint (see section 11) that hosts one weekly CSV at a time for the ECS task to pull.  
Payroll generator script creates each week's CSV and places it on the fake SFTP server.  
Create occasional corrected replacement or follow-up records.

Data volume  
Keep volume modest: thousands to low hundreds of thousands of rows are enough. The purpose is workflow realism, correctness, recoverability, and business value—not scale benchmarking.

# 13\. Client-Facing Audit Simulation

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

Networking and access decision points  
Can the required source be accessed programmatically?  
Does the vendor support full extraction?  
Does the vendor require IP allowlisting?  
Does the client require private-subnet networking by policy?  
Is fixed outbound IP required?  
What authentication mechanism is available?  
What are API rate limits?  
Is SFTP host-key information available from the vendor?  
Are all required historical records accessible?  
What delivery method does the client actually want?  
Are there data-retention requirements?  
Is the simple public-Fargate design sufficient, or does a real requirement earn the NAT Gateway escalation pattern?  
Does the payroll/timekeeping vendor actually support outbound SFTP pull, or only a manual portal export or emailed report? This determines whether Source C's SFTP-pull design is viable as-is for a given client — many SMB-tier payroll vendors only offer manual export, not vendor-hosted SFTP.

Important  
Distinguish simulated client facts from assumptions invented for the POC. The audit should explicitly determine whether a simple full-refresh file-first pattern is sufficient or whether the client's requirements justify a database-backed pattern, and whether the public-subnet networking default is sufficient or a client requirement earns the NAT Gateway escalation pattern.

# 14\. Implementation Deliverables

Infrastructure  
New isolated AWS sandbox account.  
Infrastructure-as-code for the required AWS resources where practical.  
Explicit VPC: dedicated VPC, public subnet(s), Internet Gateway, public route table, ECS/Fargate task security group with zero inbound rules.  
S3 buckets/prefixes and lifecycle configuration.  
Secrets Manager secrets for CRM/Accounting API credentials and SFTP credentials/host key.  
ECS/Fargate task definition and container image.  
EventBridge schedule.  
CloudWatch logging and basic alarms.  
SES or equivalent delivery configuration.

Application / data code  
Fake-source generators/APIs.  
Full API extraction code (CRM, Accounting).  
SFTP client extraction code (connect, host-key verification, GET, failure handling).  
Raw S3 snapshot writer.  
Transformation/reconciliation code.  
Data-quality validators.  
Business-exception logic.  
Report generation.  
Publish/promote logic.  
Delivery-adapter logic (email/secure links for POC 1).

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

Terraform structure  
Expected layout once infrastructure work begins. Do not introduce modules prematurely.

infra/terraform/  
&nbsp;&nbsp;versions.tf  
&nbsp;&nbsp;providers.tf  
&nbsp;&nbsp;variables.tf  
&nbsp;&nbsp;locals.tf  
&nbsp;&nbsp;vpc.tf  
&nbsp;&nbsp;s3.tf  
&nbsp;&nbsp;iam.tf  
&nbsp;&nbsp;secrets.tf  
&nbsp;&nbsp;ecr.tf  
&nbsp;&nbsp;ecs.tf  
&nbsp;&nbsp;eventbridge.tf  
&nbsp;&nbsp;cloudwatch.tf  
&nbsp;&nbsp;outputs.tf  
&nbsp;&nbsp;terraform.tfvars.example

# 15\. Definition of Done

A fresh AWS environment can be provisioned from documented steps, including the explicit VPC.  
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
The ECS task security group has zero inbound rules, and no security-group change accidentally exposes the task.  
Another engineer could understand the architecture, business rules, and operating procedure from the documentation.

# 16\. Deliberate Non-Goals

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
No NAT Gateway or private subnet by default — only as an earned escalation (see section 4).  
No manual upload workflow for the payroll/timekeeping feed.

# 17\. Repeatable Coresight Pattern

Document this as the reusable conceptual pattern:

Machine-accessible source → source adapter → immutable raw snapshot → transform / reconcile → validate → publish → delivery adapter

Potential source adapters: REST API, GraphQL, SFTP, S3, database.  
Potential delivery adapters: email, CSV/XLSX, file drop, dashboard, database, API.

Do NOT turn this into a generalized framework yet.

# 18\. Operational Testing

Failure and recovery scenarios  
API outage.  
API timeout.  
API authentication failure.  
SFTP outage.  
SFTP authentication failure.  
Incorrect host key.  
Missing file.  
Malformed file.  
Empty file.  
Duplicate records.  
Corrected records.  
ECS task crash.  
Validation failure.  
Publication failure.  
Notification/delivery failure.  
Rerun from raw snapshot.  
Last known-good output survives a failed run.

Networking assumption tests  
Task has outbound internet access.  
No inbound traffic is permitted.  
Expected APIs are reachable.  
Expected SFTP endpoint is reachable.  
Security-group changes do not accidentally expose the task.

# 19\. Suggested Build Order

Phase 1 — Generate realistic fake data and manually calculate the expected profitability result for a small test subset.  
Phase 2 — Build the fake field-service API, fake accounting API, and fake timekeeping SFTP server, provisioned separately from the main Coresight stack.  
Phase 3 — Provision the explicit Coresight VPC (public subnet, Internet Gateway, route table, task security group), S3, ECS/Fargate, EventBridge, and CloudWatch.  
Phase 4 — Build the full-extraction logic (CRM, Accounting, SFTP pull) and write immutable raw snapshots to S3.  
Phase 5 — Build the transform/reconciliation logic locally against raw snapshots.  
Phase 6 — Add validation checks and business-exception generation.  
Phase 7 — Generate candidate report files and implement safe publish/promotion behavior.  
Phase 8 — Add scheduled execution through EventBridge.  
Phase 9 — Add logging, alarms, and failure/recovery behavior.  
Phase 10 — Add the delivery adapter (email delivery and secure download links for POC 1).  
Phase 11 — Run failure/recovery tests and intentionally inject source corrections/schema defects, including SFTP failure modes.  
Phase 12 — Produce the simulated Audit, runbook, and client handoff documentation.  
Phase 13 — Review the project as a Coresight engagement: what was difficult, what should the Audit have discovered earlier, what could be standardized, and what should remain client-specific?

Success criterion  
The project is successful if it demonstrates that one recurring manual reporting process can be converted into a small, understandable, low-cost AWS batch workflow that reliably produces trustworthy files, preserves an auditable copy of every source extract, clearly surfaces exceptions, and requires very little operational care.

# 20\. Architectural Principle

> Coresight should prefer the smallest architecture that is secure, supportable, auditable, and sufficient for the client's actual requirements.

> Complexity must be earned by a requirement.

The goal of POC 1 is not to imitate an enterprise data platform. The goal is to fully exercise one small production-quality reporting automation pattern that is inexpensive, understandable, testable, and transferable to a client.

#!/usr/bin/env python3
"""Simulate the weekly payroll presigned-URL upload flow for the Coresight file-based POC.

Models what happens in AWS without making any AWS calls: a scheduled Lambda mints a
short-lived presigned S3 POST URL scoped to that week's inbound key and emails it to
the ops manager via SES; the ops manager opens the link, picks the file, and uploads
directly to S3. See docs/project-overview.md section 2 (Source C) for why this was
chosen over AWS Transfer Family (SFTP) or SES inbound email receiving.

Reads the already-generated weekly file from payroll/<week>.csv (produced by
generate_base_data.py) and, on a successful "upload", copies it into
payroll_inbound/<week>.csv - the directory that stands in for the real S3 inbound
prefix the batch task reads from. Pass --simulate-missed-upload to model the ops
manager not uploading that week at all (see known_defects.md: "missing payroll file
for one scheduled run").

Usage:
    python fake_sources/data_gen/simulate_payroll_upload.py --week 2025-W33
    python fake_sources/data_gen/simulate_payroll_upload.py --week 2025-W35 --simulate-missed-upload
"""

import argparse
import json
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR.parent / "data"
LINK_TTL_DAYS = 4


def load_json(path):
    return json.loads(path.read_text()) if path.exists() else []


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def generate_presigned_post(bucket, key, ttl_days):
    """Stand-in for boto3 s3_client.generate_presigned_post(...). Produces a
    realistic-looking response shape but is not a working credential - no AWS
    call is made."""
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now() + timedelta(days=ttl_days)
    return {
        "url": f"https://{bucket}.s3.amazonaws.com/",
        "fields": {"key": key, "X-Amz-Signature": token},
        "expires_at": expires_at.isoformat(timespec="seconds"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", required=True, help="ISO week label, e.g. 2025-W33")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--bucket", default="coresight-poc-payroll-inbound")
    parser.add_argument("--ops-manager-email", default="ops.manager@abcmechanical.example")
    parser.add_argument("--simulate-missed-upload", action="store_true",
                         help="Model the ops manager not uploading this week at all.")
    args = parser.parse_args()

    source_path = args.data_dir / "payroll" / f"{args.week}.csv"
    inbound_dir = args.data_dir / "payroll_inbound"
    inbound_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.data_dir / "payroll_uploads_log.json"
    log = load_json(log_path)

    key = f"payroll-inbound/{args.week}.csv"
    presigned = generate_presigned_post(args.bucket, key, LINK_TTL_DAYS)

    print(f"[EventBridge] weekly payroll upload reminder fired for {args.week}")
    print(f"[Lambda] generated presigned POST for s3://{args.bucket}/{key} "
          f"(expires {presigned['expires_at']})")
    print(f"[SES] emailed upload link to {args.ops_manager_email}")

    if args.simulate_missed_upload:
        print("[ops manager] did not upload this week - simulating a missed payroll file")
        event = {
            "week": args.week, "status": "missed", "uploaded_at": None,
            "presigned_url_expires_at": presigned["expires_at"],
            "ops_manager_email": args.ops_manager_email,
        }
    else:
        if not source_path.exists():
            parser.error(f"no generated payroll file for week {args.week} at {source_path} "
                         f"(run generate_base_data.py first, or check the week label)")
        dest_path = inbound_dir / f"{args.week}.csv"
        shutil.copy2(source_path, dest_path)
        print(f"[ops manager] uploaded {source_path.name} via presigned URL -> {dest_path}")
        event = {
            "week": args.week, "status": "uploaded",
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "presigned_url_expires_at": presigned["expires_at"],
            "ops_manager_email": args.ops_manager_email,
        }

    log.append(event)
    write_json(log_path, log)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Maintenance tool that keeps the AskPlex DynamoDB persistence table
clean.

The skill partitions playback state per (user, device). At runtime the
Lambda already deletes a device's row as soon as its session ends with
nothing left to resume (see Controller.clear_persisted_state), so the
table normally only holds rows for active/resumable sessions.

This script removes the rows the runtime cannot reach:

  * Legacy rows written before persistence was partitioned per device.
    These use a bare user id (no ":" in the partition key) and are no
    longer read by the skill.

  * Abandoned sessions: rows with no resumable playback (no active
    session and an empty playlist) that were left behind because the
    user simply stopped interacting instead of finishing the playlist.

Run it ad hoc, or on a schedule (e.g. an EventBridge-triggered Lambda /
a cron job) to keep the table tidy.

Usage:

    # Dry run (default table/region from the same env vars the skill
    # uses); shows what would be deleted without changing anything.
    python3 cleanup_persistence.py --dry-run

    # Actually delete.
    python3 cleanup_persistence.py

    # Override table / region explicitly.
    python3 cleanup_persistence.py \
        --table my-table --region eu-central-1
"""

import argparse
import os
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description="Clean up the AskPlex DynamoDB persistence table.",
    )

    parser.add_argument(
        "--table",
        default=os.environ.get("DYNAMODB_PERSISTENCE_TABLE_NAME"),
        help="DynamoDB table name "
             "(default: $DYNAMODB_PERSISTENCE_TABLE_NAME).",
    )

    parser.add_argument(
        "--region",
        default=os.environ.get("DYNAMODB_PERSISTENCE_REGION"),
        help="AWS region "
             "(default: $DYNAMODB_PERSISTENCE_REGION).",
    )

    parser.add_argument(
        "--partition-key-name",
        default="id",
        help="Partition key attribute name (default: id).",
    )

    parser.add_argument(
        "--attribute-name",
        default="attributes",
        help="Attribute container name (default: attributes).",
    )

    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Do not delete legacy per-account rows "
             "(partition key without a ':').",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without deleting.",
    )

    return parser.parse_args()


def is_stale(item, key_name, attr_name, keep_legacy):
    """
    Decide whether a persistence row can be safely removed.

    Returns a (stale: bool, reason: str) tuple.
    """

    key = item.get(key_name, "")

    # Legacy row from before the per-device partitioning.
    if not keep_legacy and ":" not in str(key):
        return True, "legacy per-account key"

    attributes = item.get(attr_name) or {}
    playback_info = attributes.get("playback_info") or {}

    # A resumable session is one that is either actively playing or
    # still has tracks queued to resume.
    in_session = bool(playback_info.get("in_playback_session"))
    playlist = playback_info.get("playlist") or {}

    if not in_session and len(playlist) == 0:
        return True, "no active or resumable session"

    return False, ""


def main():
    args = parse_args()

    if not args.table:
        print(
            "error: no table name given "
            "(--table or $DYNAMODB_PERSISTENCE_TABLE_NAME)",
            file=sys.stderr,
        )
        return 2

    import boto3

    resource = boto3.resource(
        "dynamodb",
        region_name=args.region,
    )
    table = resource.Table(args.table)

    scanned = 0
    deleted = 0

    scan_kwargs = {}

    while True:
        response = table.scan(**scan_kwargs)

        for item in response.get("Items", []):
            scanned += 1

            stale, reason = is_stale(
                item,
                args.partition_key_name,
                args.attribute_name,
                args.keep_legacy,
            )

            if not stale:
                continue

            key_value = item.get(args.partition_key_name)

            if args.dry_run:
                print(f"[dry-run] would delete {key_value} ({reason})")
                deleted += 1
                continue

            table.delete_item(
                Key={args.partition_key_name: key_value},
            )
            print(f"deleted {key_value} ({reason})")
            deleted += 1

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key

    verb = "would remove" if args.dry_run else "removed"
    print(f"\nScanned {scanned} rows, {verb} {deleted}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

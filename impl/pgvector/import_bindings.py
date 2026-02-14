#!/usr/bin/env python3
"""
Import bindings from a JSON staging file into the abra database.

IMPORTANT: No PII (email, phone, address) in pgvector. Contact details go to CRM only.

Staging file format (array of entries):
[
  {
    "source_file": "1-20-26-leanne-ussher.txt",
    "content": "full text of the note (PII stripped)...",
    "note_date": "2026-01-20",
    "bindings": [
      {
        "scope": "golda",
        "name": "leanne-ussher",
        "relationship": "IS",
        "target_type": "text",
        "target_ref": "Leanne Ussher",
        "qualifier": null,
        "permanence": "INTRINSIC"
      },
      {
        "scope": "golda",
        "name": "leanne-ussher",
        "relationship": "ABOUT",
        "target_type": "content",
        "target_ref": "__CONTENT_ID__",
        "qualifier": "meeting notes",
        "permanence": "CURRENT"
      },
      {
        "scope": "golda",
        "name": "leanne-ussher",
        "relationship": "HAS",
        "target_type": "text",
        "target_ref": "contact:pending-crm",
        "qualifier": null,
        "permanence": "CURRENT"
      },
      {
        "scope": "golda",
        "name": "lt",
        "relationship": "RELATED",
        "target_type": "content",
        "target_ref": "__CONTENT_ID__",
        "qualifier": "contact - currency design",
        "permanence": "EPHEMERAL"
      }
    ]
  }
]

target_ref of "__CONTENT_ID__" gets replaced with the actual content.id after insertion.
"""
import os
import re
import sys
import json
import argparse
import psycopg2
from dotenv import load_dotenv

load_dotenv()

PG_HOST = os.getenv("PG_HOST", "10.0.0.100")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER", "cobox")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DATABASE = os.getenv("PG_DATABASE", "abra")

# Patterns that suggest PII in a binding target_ref
PII_PATTERNS = [
    re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),  # email
    re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),  # phone
    re.compile(r'\b\d{5}(-\d{4})?\b'),  # zip code
]


def check_pii(target_ref):
    """Return True if target_ref appears to contain PII."""
    for pattern in PII_PATTERNS:
        if pattern.search(target_ref):
            return True
    return False


def import_staging(staging_file, dry_run=False):
    with open(staging_file) as f:
        entries = json.load(f)

    print(f"Loaded {len(entries)} entries from {staging_file}")

    pii_warnings = []

    if dry_run:
        for entry in entries:
            print(f"\n  {entry['source_file']} ({entry.get('note_date', '?')})")
            for b in entry['bindings']:
                qual = f' "{b["qualifier"]}"' if b.get('qualifier') else ''
                pii_flag = " *** PII DETECTED - WILL SKIP ***" if check_pii(b.get('target_ref', '')) else ''
                print(f"    {b['name']} {b['relationship']} [{b['target_type']}]{qual} ({b['permanence']}){pii_flag}")
                if pii_flag:
                    pii_warnings.append(f"{entry['source_file']}: {b['name']} {b['relationship']} {b['target_ref'][:40]}")
        if pii_warnings:
            print(f"\n  WARNING: {len(pii_warnings)} bindings contain PII and will be skipped on import.")
            print("  PII belongs in the CRM, not pgvector. Use 'contact:pending-crm' instead.")
        print(f"\nDry run — nothing written. Use --confirm to import.")
        return

    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname=PG_DATABASE
    )
    cur = conn.cursor()

    imported = 0
    skipped_pii = 0
    for entry in entries:
        # Insert content
        cur.execute(
            "INSERT INTO content (source_file, content, note_date) VALUES (%s, %s, %s) RETURNING id",
            (entry['source_file'], entry['content'], entry.get('note_date'))
        )
        content_id = cur.fetchone()[0]

        # Insert bindings
        for b in entry['bindings']:
            target_ref = b['target_ref']
            if target_ref == '__CONTENT_ID__':
                target_ref = str(content_id)

            # Skip bindings that contain PII
            if check_pii(target_ref):
                print(f"  SKIPPED (PII): {b['name']} {b['relationship']} {target_ref[:40]}...")
                skipped_pii += 1
                continue

            cur.execute(
                """INSERT INTO bindings (scope, name, relationship, target_type, target_ref, qualifier, permanence, source_date, catcode)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (b['scope'], b['name'], b['relationship'], b['target_type'],
                 target_ref, b.get('qualifier'), b.get('permanence', 'CURRENT'),
                 entry.get('note_date'), b.get('catcode'))
            )

        imported += 1
        conn.commit()

    cur.close()
    conn.close()
    print(f"\nImported {imported} entries with bindings.")
    if skipped_pii:
        print(f"Skipped {skipped_pii} bindings containing PII. These belong in the CRM.")


def main():
    parser = argparse.ArgumentParser(description='Import bindings from staging JSON')
    parser.add_argument('staging_file', help='Path to staging JSON file')
    parser.add_argument('--confirm', action='store_true', help='Actually write to database (default is dry run)')
    args = parser.parse_args()

    import_staging(args.staging_file, dry_run=not args.confirm)


if __name__ == "__main__":
    main()

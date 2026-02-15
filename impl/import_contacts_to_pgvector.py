#!/usr/bin/env python3
"""
Import LinkedIn Connections.csv and/or Google Contacts.csv into pgvector
as searchable content blobs (scrubbed of PII).

Strips emails, phone numbers, addresses. Keeps: name, company, position, date.
Stores as chunked content blobs under golda/contacts/linkedin-full (a0010103).

Usage:
    cd /opt/shared/repos/abra/impl

    # Dry run (default) — shows what would be imported
    .venv/bin/python import_contacts_to_pgvector.py ~/Connections.csv ~/Contacts.csv

    # Actually import
    .venv/bin/python import_contacts_to_pgvector.py ~/Connections.csv ~/Contacts.csv --confirm

    # LinkedIn only
    .venv/bin/python import_contacts_to_pgvector.py ~/Connections.csv --confirm

    # Replace existing (deletes old chunks first)
    .venv/bin/python import_contacts_to_pgvector.py ~/Connections.csv ~/Contacts.csv --confirm --replace
"""
import csv
import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pgvector'))
from write_binding import AbraWriter

CATCODE = "a0010103"
CATCODE_PARENT = "a00101"
CATCODE_LABEL = "golda/contacts/linkedin-full"
BINDING_NAME = "linkedin-contacts-full"
CHUNK_SIZE = 200


def load_linkedin(path):
    """Load LinkedIn Connections.csv, return list of scrubbed strings."""
    rows = []
    with open(path, "r") as f:
        lines = f.readlines()
        header_idx = None
        for i, line in enumerate(lines):
            if line.startswith("First Name,"):
                header_idx = i
                break
        if header_idx is None:
            print(f"  WARNING: no header found in {path}")
            return rows
        reader = csv.DictReader(lines[header_idx:])
        for row in reader:
            first = row.get("First Name", "").strip()
            last = row.get("Last Name", "").strip()
            company = row.get("Company", "").strip()
            position = row.get("Position", "").strip()
            connected = row.get("Connected On", "").strip()
            if not first and not last:
                continue
            name = f"{first} {last}".strip()
            parts = [name]
            if position:
                parts.append(position)
            if company:
                parts.append(f"at {company}")
            if connected:
                parts.append(f"(connected {connected})")
            rows.append(" — ".join(parts))
    return rows


def load_google(path):
    """Load Google Contacts.csv, return list of scrubbed strings (only those with company/title)."""
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            first = row.get("FirstName", "").strip()
            last = row.get("LastName", "").strip()
            company = row.get("Companies", "").strip()
            title = row.get("Title", "").strip()
            if not first and not last:
                continue
            if company == "null":
                company = ""
            name = f"{first} {last}".strip()
            if not name:
                continue
            if not company and not title:
                continue
            parts = [name]
            if title:
                parts.append(title)
            if company:
                parts.append(f"at {company}")
            rows.append(" — ".join(parts))
    return rows


def main():
    parser = argparse.ArgumentParser(description="Import contacts to pgvector (scrubbed, no PII)")
    parser.add_argument("files", nargs="+", help="CSV files (LinkedIn Connections.csv and/or Google Contacts.csv)")
    parser.add_argument("--confirm", action="store_true", help="Actually write (default is dry run)")
    parser.add_argument("--replace", action="store_true", help="Delete existing contact chunks first")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help=f"Contacts per chunk (default {CHUNK_SIZE})")
    args = parser.parse_args()

    all_rows = []
    for path in args.files:
        if not os.path.exists(path):
            print(f"File not found: {path}")
            sys.exit(1)
        # Detect type by header
        with open(path) as f:
            sample = f.read(500)
        if "First Name,Last Name,URL" in sample:
            rows = load_linkedin(path)
            print(f"LinkedIn: {len(rows)} connections from {path}")
        elif "Source,FirstName,LastName" in sample:
            rows = load_google(path)
            print(f"Google: {len(rows)} contacts with company/title from {path}")
        else:
            print(f"Unknown CSV format: {path}")
            continue
        all_rows.extend(rows)

    print(f"Total: {len(all_rows)} entries (scrubbed, no emails/phones)")

    chunks = [all_rows[i:i + args.chunk_size] for i in range(0, len(all_rows), args.chunk_size)]
    print(f"Will store as {len(chunks)} chunks of ~{args.chunk_size}")

    if not args.confirm:
        print("\nDry run. Sample entries:")
        for row in all_rows[:10]:
            print(f"  {row}")
        print(f"  ... and {len(all_rows) - 10} more")
        print("\nRun with --confirm to write.")
        return

    writer = AbraWriter()

    # Ensure catcode exists
    writer.register_catcode(CATCODE, CATCODE_PARENT, CATCODE_LABEL)

    # Delete old chunks if replacing
    if args.replace:
        cur = writer.conn.cursor()
        cur.execute("DELETE FROM content WHERE catcode = %s AND source_file LIKE 'contacts-full-list-chunk-%'", (CATCODE,))
        old_content = cur.rowcount
        cur.execute("DELETE FROM bindings WHERE scope = 'golda' AND name = %s", (BINDING_NAME,))
        old_bindings = cur.rowcount
        writer.conn.commit()
        cur.close()
        print(f"Replaced: deleted {old_content} old chunks, {old_bindings} old bindings")

    # Store chunks
    content_ids = []
    for i, chunk in enumerate(chunks):
        content = f"LinkedIn and Google contacts (chunk {i + 1}/{len(chunks)})\n"
        content += "Scrubbed: no emails or phone numbers. For PII see CRM.\n\n"
        content += "\n".join(chunk)
        cid = writer.store_content(
            f"contacts-full-list-chunk-{i + 1}.csv",
            content,
            note_date="2025-02-15",
            catcode=CATCODE,
        )
        content_ids.append(cid)
        print(f"  Chunk {i + 1}: {len(chunk)} entries -> content {cid}")

    # Create bindings
    writer.write_binding("golda", BINDING_NAME, "IS", "text",
        "Full LinkedIn + Google contacts list (scrubbed, no PII)",
        permanence="INTRINSIC", source_date="2025-02-15", catcode=CATCODE)
    for i, cid in enumerate(content_ids):
        writer.write_binding("golda", BINDING_NAME, "ABOUT", "content",
            str(cid),
            qualifier=f"contacts list chunk {i + 1}/{len(chunks)}",
            source_date="2025-02-15", catcode=CATCODE)

    writer.close()
    print(f"\nDone. {len(all_rows)} contacts in {len(chunks)} chunks.")
    print(f"Search with: abra search \"healthcare\"")
    print(f"Read with:   abra read linkedin-contacts-full")


if __name__ == "__main__":
    main()

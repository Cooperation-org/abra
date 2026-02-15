#!/usr/bin/env python3
"""
Import LinkedIn Connections.csv and Google/LinkedIn Contacts.csv into Odoo CRM + abra pgvector.

PII (name, email, phone, company, title) → Odoo CRM
Bindings (pet name, IS, HAS crm:odoo/contact/ID, HAS uri:linkedin) → pgvector
All contacts placed at catcode a0010101 (golda/contacts).

Deduplicates by email (primary) then by normalized name.
Dry run by default — use --confirm to write.

Usage:
    python import_linkedin.py ~/Connections.csv ~/Contacts.csv
    python import_linkedin.py ~/Connections.csv ~/Contacts.csv --confirm
"""
import csv
import os
import re
import sys
import argparse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

CATCODE_CONTACTS = "a0010101"  # golda/contacts


def normalize_name(first, last):
    """Lowercase pet name: first-last, stripped of non-alpha."""
    first = (first or "").strip().lower()
    last = (last or "").strip().lower()
    # Remove non-alpha except hyphens
    first = re.sub(r'[^a-z-]', '', first)
    last = re.sub(r'[^a-z-]', '', last)
    if first and last:
        return f"{first}-{last}"
    return first or last or None


def full_name(first, last):
    first = (first or "").strip()
    last = (last or "").strip()
    if first and last:
        return f"{first} {last}"
    return first or last or None


def parse_connections(path):
    """Parse LinkedIn Connections.csv. Returns list of contact dicts."""
    contacts = []
    with open(path, encoding='utf-8') as f:
        # Skip the notes header (lines before the actual CSV header)
        for line in f:
            if line.startswith("First Name,"):
                break
        reader = csv.DictReader(f, fieldnames=[
            "First Name", "Last Name", "URL", "Email Address",
            "Company", "Position", "Connected On"
        ])
        for row in reader:
            first = (row.get("First Name") or "").strip()
            last = (row.get("Last Name") or "").strip()
            name = full_name(first, last)
            if not name:
                continue
            contacts.append({
                "name": name,
                "pet_name": normalize_name(first, last),
                "email": (row.get("Email Address") or "").strip() or None,
                "company": (row.get("Company") or "").strip() or None,
                "title": (row.get("Position") or "").strip() or None,
                "phone": None,
                "linkedin_url": (row.get("URL") or "").strip() or None,
                "source": "linkedin",
            })
    return contacts


def parse_contacts(path):
    """Parse Google/LinkedIn Contacts.csv. Returns list of contact dicts."""
    contacts = []
    with open(path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            first = (row.get("FirstName") or "").strip()
            last = (row.get("LastName") or "").strip()
            name = full_name(first, last)
            emails_raw = (row.get("Emails") or "").strip()
            # Take first email from comma-separated list
            emails = [e.strip() for e in emails_raw.split(",") if e.strip()]
            email = emails[0] if emails else None
            company = (row.get("Companies") or "").strip()
            if company == "null":
                company = None
            phone_raw = (row.get("PhoneNumbers") or "").strip()
            phones = [p.strip() for p in phone_raw.split(",") if p.strip()]
            phone = phones[0] if phones else None
            linkedin_url = None
            profiles = (row.get("Profiles") or "").strip()
            if "linkedin.com" in profiles:
                for part in profiles.split(","):
                    part = part.strip()
                    if "linkedin.com" in part:
                        linkedin_url = part
                        break
            # Skip entries with no name and no email
            if not name and not email:
                continue
            # Use email-derived name as fallback
            if not name and email:
                name = email.split("@")[0]
            pet = normalize_name(first, last)
            if not pet and email:
                pet = re.sub(r'[^a-z0-9-]', '', email.split("@")[0].lower()) or None
            contacts.append({
                "name": name,
                "pet_name": pet,
                "email": email,
                "company": company,
                "title": (row.get("Title") or "").strip() or None,
                "phone": phone,
                "linkedin_url": linkedin_url,
                "source": row.get("Source", "unknown").strip().lower(),
            })
    return contacts


def dedup(all_contacts):
    """Deduplicate by email (primary) then normalized name. LinkedIn source wins on merge."""
    by_email = {}
    by_name = {}
    deduped = []

    for c in all_contacts:
        email = (c["email"] or "").lower()
        pet = c["pet_name"]

        if email and email in by_email:
            # Merge: prefer linkedin source for URLs, keep richer data
            existing = by_email[email]
            if not existing["linkedin_url"] and c["linkedin_url"]:
                existing["linkedin_url"] = c["linkedin_url"]
            if not existing["company"] and c["company"]:
                existing["company"] = c["company"]
            if not existing["title"] and c["title"]:
                existing["title"] = c["title"]
            if not existing["phone"] and c["phone"]:
                existing["phone"] = c["phone"]
            if c["source"] == "linkedin" and existing["source"] != "linkedin":
                existing["source"] = "linkedin"
            continue

        if not email and pet and pet in by_name:
            existing = by_name[pet]
            if not existing["linkedin_url"] and c["linkedin_url"]:
                existing["linkedin_url"] = c["linkedin_url"]
            if not existing["company"] and c["company"]:
                existing["company"] = c["company"]
            if not existing["title"] and c["title"]:
                existing["title"] = c["title"]
            continue

        deduped.append(c)
        if email:
            by_email[email] = c
        if pet:
            by_name[pet] = c

    return deduped


def do_import(contacts, dry_run=True):
    """Import contacts to Odoo CRM + pgvector bindings."""
    if dry_run:
        print(f"\n  DRY RUN — {len(contacts)} contacts to import\n")
        no_email = sum(1 for c in contacts if not c["email"])
        no_name = sum(1 for c in contacts if not c["pet_name"])
        sources = {}
        for c in contacts:
            sources[c["source"]] = sources.get(c["source"], 0) + 1
        print(f"  Sources: {sources}")
        print(f"  Missing email: {no_email}")
        print(f"  Missing pet name: {no_name}")
        print(f"\n  First 20:")
        for c in contacts[:20]:
            email_str = c['email'] or '(no email)'
            company_str = c['company'] or ''
            print(f"    {c['pet_name'] or '???':30s} {email_str:40s} {company_str}")
        print(f"\n  Use --confirm to write to Odoo + pgvector.")
        return

    # Real import
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'connectors', 'odoo'))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pgvector'))
    from connector import OdooConnector
    from write_binding import AbraWriter

    crm = OdooConnector()
    if not crm.is_ready():
        print("ERROR: CRM not ready. Check ~/.abra/sources.yaml")
        sys.exit(1)

    writer = AbraWriter()
    created = 0
    skipped = 0
    errors = 0

    for i, c in enumerate(contacts):
        try:
            # Check if contact already exists in Odoo (by email)
            existing = None
            if c["email"]:
                found = crm.find_contact(email=c["email"])
                if found:
                    existing = found[0]

            if existing:
                skipped += 1
                continue

            # Create in Odoo (PII goes here)
            odoo_id = crm.create_contact(
                name=c["name"],
                email=c["email"],
                phone=c["phone"],
                company=c["company"],
                catcode=CATCODE_CONTACTS,
                notes=f"Imported from {c['source']}. Title: {c.get('title') or 'n/a'}",
            )
            if isinstance(odoo_id, list):
                odoo_id = odoo_id[0]

            # Create bindings in pgvector (no PII)
            if c["pet_name"]:
                writer.write_binding("golda", c["pet_name"], "IS", "text",
                                     c["name"], permanence="INTRINSIC",
                                     catcode=CATCODE_CONTACTS)
                writer.write_binding("golda", c["pet_name"], "HAS", "uri",
                                     f"crm:odoo/contact/{odoo_id}",
                                     permanence="CURRENT", catcode=CATCODE_CONTACTS)
                if c["linkedin_url"]:
                    writer.write_binding("golda", c["pet_name"], "HAS", "uri",
                                         c["linkedin_url"],
                                         permanence="CURRENT", catcode=CATCODE_CONTACTS)

            created += 1
            if (i + 1) % 100 == 0:
                print(f"  ... {i + 1}/{len(contacts)} processed ({created} created, {skipped} skipped)")

        except Exception as e:
            print(f"  ERROR on {c['name']}: {e}")
            errors += 1

    writer.close()
    print(f"\nDone: {created} created, {skipped} already existed, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Import LinkedIn + Google contacts into Odoo + abra")
    parser.add_argument("files", nargs="+", help="CSV files to import (Connections.csv and/or Contacts.csv)")
    parser.add_argument("--confirm", action="store_true", help="Actually write (default is dry run)")
    args = parser.parse_args()

    all_contacts = []
    for path in args.files:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            print(f"File not found: {path}")
            sys.exit(1)

        # Detect format by header
        with open(path, encoding='utf-8') as f:
            header_area = f.read(500)

        if "First Name,Last Name,URL,Email Address" in header_area:
            contacts = parse_connections(path)
            print(f"Parsed {len(contacts)} from {path} (LinkedIn Connections format)")
        elif "Source,FirstName,LastName" in header_area:
            contacts = parse_contacts(path)
            print(f"Parsed {len(contacts)} from {path} (Google/LinkedIn Contacts format)")
        else:
            print(f"Unknown CSV format in {path}")
            sys.exit(1)

        all_contacts.extend(contacts)

    print(f"Total before dedup: {len(all_contacts)}")
    all_contacts = dedup(all_contacts)
    print(f"Total after dedup: {len(all_contacts)}")

    do_import(all_contacts, dry_run=not args.confirm)


if __name__ == "__main__":
    main()

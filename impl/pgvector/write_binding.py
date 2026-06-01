#!/usr/bin/env python3
"""
Write bindings and content directly to abra pgvector store, one at a time.

Usage from a processing session:
    from write_binding import AbraWriter
    writer = AbraWriter()

    # Store a note blob
    content_id = writer.store_content("1-20-26-leanne.txt", "note text...", note_date="2026-01-20")

    # Create bindings
    writer.write_binding("golda", "leanne-ussher", "IS", "text", "Leanne Ussher", permanence="INTRINSIC")
    writer.write_binding("golda", "leanne-ussher", "ABOUT", "content", str(content_id), qualifier="meeting notes")
    writer.write_binding("golda", "lt", "RELATED", "content", str(content_id), qualifier="contact - currency design")

    # Check if a name already exists
    existing = writer.find_name("golda", "leanne")  # returns list of matching names

Also usable as CLI:
    python write_binding.py --scope golda --name leanne-ussher --rel IS --target-type text --target-ref "Leanne Ussher"
"""
import os
import re
import sys
import argparse
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

PG_HOST = os.getenv("PG_HOST", "10.0.0.100")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER", "cobox")
PG_PASSWORD = os.getenv("PG_PASSWORD", "")
PG_DATABASE = os.getenv("PG_DATABASE", "abra")

PII_PATTERNS = [
    re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),
    re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
    re.compile(r'\b\d{5}(-\d{4})?\b'),
]


def check_pii(text):
    for pattern in PII_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _default_writer_uri():
    """URI representing the writer when none is supplied.
    Looks up env ABRA_WRITER_URI first, falls back to urn:abra:local:<USER>."""
    env = os.getenv("ABRA_WRITER_URI")
    if env:
        return env
    user = os.getenv("USER") or os.getenv("USERNAME") or "unknown"
    return f"urn:abra:local:{user}"


class AbraWriter:
    def __init__(self, writer_uri=None):
        """writer_uri identifies who is writing (provenance, per 2026-05 design).
        Defaults to ABRA_WRITER_URI env or urn:abra:local:<USER>."""
        self.writer_uri = writer_uri or _default_writer_uri()
        self.conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, user=PG_USER,
            password=PG_PASSWORD, dbname=PG_DATABASE
        )

    def store_content(self, source_file, content, note_date=None, catcode=None):
        """Store a content blob. Returns content ID.
        Populates both `catcode` (singular, legacy) and `catcodes` (array, current spec).
        Stamps created_by from self.writer_uri."""
        cur = self.conn.cursor()
        catcodes = [catcode] if catcode else []
        cur.execute(
            "INSERT INTO content (source_file, content, note_date, catcode, catcodes, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (source_file, content, note_date, catcode, catcodes, self.writer_uri)
        )
        content_id = cur.fetchone()[0]
        self.conn.commit()
        cur.close()
        return content_id

    def write_binding(self, scope, name, rel=None, target_type=None, target_ref=None,
                      qualifier=None, permanence="CURRENT", source_date=None, catcode=None,
                      relationship=None):
        # accept either 'rel' or 'relationship'
        relationship = rel or relationship
        """Write a single binding. Rejects PII in target_ref.
        Populates both `catcode` (legacy) and `catcodes` (array, current spec).
        Stamps created_by from self.writer_uri."""
        if check_pii(target_ref):
            print(f"  REJECTED (PII detected): {name} {relationship} {target_ref[:40]}...")
            return None

        cur = self.conn.cursor()
        catcodes = [catcode] if catcode else []
        cur.execute(
            """INSERT INTO bindings
               (scope, name, relationship, target_type, target_ref, qualifier, permanence,
                source_date, catcode, catcodes, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (scope, name, relationship, target_type, target_ref,
             qualifier, permanence, source_date, catcode, catcodes, self.writer_uri)
        )
        binding_id = cur.fetchone()[0]
        self.conn.commit()
        cur.close()
        return binding_id

    def register_catcode(self, catcode, parent_catcode, label):
        """Register a position in the catcode space. Returns catcode."""
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO catcode_registry (catcode, parent_catcode, label)
               VALUES (%s, %s, %s)
               ON CONFLICT (catcode) DO UPDATE SET label = EXCLUDED.label
               RETURNING catcode""",
            (catcode, parent_catcode, label)
        )
        result = cur.fetchone()[0]
        self.conn.commit()
        cur.close()
        return result

    def find_catcode(self, prefix):
        """Find catcodes by prefix. Returns list of (catcode, parent_catcode, label)."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT catcode, parent_catcode, label FROM catcode_registry WHERE catcode LIKE %s ORDER BY catcode",
            (f"{prefix}%",)
        )
        results = cur.fetchall()
        cur.close()
        return results

    def next_catcode(self, parent_catcode):
        """Get next sequential catcode under a parent. 2-char alphanumeric levels (00-zz)."""
        cur = self.conn.cursor()
        parent_len = len(parent_catcode)
        child_len = parent_len + 2
        cur.execute(
            "SELECT catcode FROM catcode_registry WHERE parent_catcode = %s ORDER BY catcode DESC LIMIT 1",
            (parent_catcode,)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return parent_catcode + "01"
        last = row[0][parent_len:child_len]
        # Increment alphanumeric: 00-09, 0a-0z, 10-19, ... zz
        chars = "0123456789abcdefghijklmnopqrstuvwxyz"
        idx = chars.index(last[0]) * 36 + chars.index(last[1]) + 1
        if idx >= 1296:
            raise ValueError(f"Catcode space exhausted under {parent_catcode}")
        return parent_catcode + chars[idx // 36] + chars[idx % 36]

    def delete_catcode(self, catcode):
        """Delete a catcode and cascade: removes subtree and all referencing bindings/content."""
        cur = self.conn.cursor()
        # Remove bindings and content referencing this subtree
        cur.execute("DELETE FROM bindings WHERE catcode LIKE %s", (f"{catcode}%",))
        cur.execute("DELETE FROM content WHERE catcode LIKE %s", (f"{catcode}%",))
        # CASCADE on FK handles subtree in registry
        cur.execute("DELETE FROM catcode_registry WHERE catcode = %s", (catcode,))
        self.conn.commit()
        cur.close()

    def rename_name(self, scope, old_name, new_name):
        """Rename a pet name. Safe — nothing uses name as a foreign key."""
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE bindings SET name = %s WHERE scope = %s AND name = %s",
            (new_name, scope, old_name)
        )
        count = cur.rowcount
        self.conn.commit()
        cur.close()
        return count

    def set_hot(self, scope, name, priority=0, days=30):
        """Mark a name as hot in a scope. Expires after `days` days (default 30)."""
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO hot_tags (scope, name, priority, expires_at)
               VALUES (%s, %s, %s, NOW() + make_interval(days => %s))
               ON CONFLICT (scope, name) DO UPDATE SET
                   priority = EXCLUDED.priority,
                   expires_at = EXCLUDED.expires_at,
                   added_at = NOW()""",
            (scope, name, priority, days)
        )
        self.conn.commit()
        cur.close()

    def unset_hot(self, scope, name):
        """Remove a name from the hot list."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM hot_tags WHERE scope = %s AND name = %s", (scope, name))
        count = cur.rowcount
        self.conn.commit()
        cur.close()
        return count

    def find_name(self, scope, name_prefix):
        """Find existing names matching a prefix. Returns list of (name, relationship, target_ref) tuples."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT DISTINCT name, relationship, target_ref FROM bindings WHERE scope = %s AND name LIKE %s ORDER BY name",
            (scope, f"{name_prefix}%")
        )
        results = cur.fetchall()
        cur.close()
        return results

    def close(self):
        self.conn.close()


def main():
    parser = argparse.ArgumentParser(description='Write a single binding to abra')
    parser.add_argument('--scope', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--rel', required=True, help='Relationship type (IS, HAS, ABOUT, RELATED, etc)')
    parser.add_argument('--target-type', required=True, help='text, content, uri, name')
    parser.add_argument('--target-ref', required=True)
    parser.add_argument('--qualifier', default=None)
    parser.add_argument('--permanence', default='CURRENT')
    parser.add_argument('--catcode', default=None)
    args = parser.parse_args()

    writer = AbraWriter()
    bid = writer.write_binding(args.scope, args.name, args.rel, args.target_type,
                               args.target_ref, args.qualifier, args.permanence, catcode=args.catcode)
    if bid:
        print(f"Created binding {bid}: {args.name} {args.rel} [{args.target_type}] {args.target_ref}")
    writer.close()


if __name__ == "__main__":
    main()

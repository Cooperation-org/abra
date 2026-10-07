#!/usr/bin/env python3
"""
Write bindings and content directly to the abra store, one at a time.

Usage from a processing session:
    from write_binding import AbraWriter
    writer = AbraWriter()

    # Store a note blob
    content_id = writer.store_content(source_file, text, note_date=None, catcode=catcode)

    # Create bindings
    writer.write_binding(scope, name, "IS", "text", what_it_is, permanence="INTRINSIC")
    writer.write_binding(scope, name, "ABOUT", "content", str(content_id), qualifier=summary)

    # Check if a name already exists
    existing = writer.find_name(scope, name_prefix)  # returns list of matching names

Also usable as CLI:
    python write_binding.py --scope <scope> --name <name> --rel IS --target-type text --target-ref "<what it is>"
"""
import re
import argparse

import db
import embedding
from instance import default_writer_uri

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


def embed(text):
    """Embedding for a content blob as a list of floats. Returns None when the
    model is unavailable (a service identity without sentence-transformers, no
    model cache) so a write never fails on it; `abra reindex` fills those in."""
    if not text or not text.strip():
        return None
    try:
        return embedding.encode(text)
    except Exception as e:
        print(f"  warning: no embedding ({e}); run `abra reindex` to make it searchable")
        return None


class AbraWriter:
    def __init__(self, writer_uri=None, dsn=None):
        """writer_uri identifies who is writing (provenance).
        Defaults to ABRA_WRITER_URI env or urn:abra:local:<user>.

        dsn: explicit connection URL (postgresql://... or sqlite:///...), for
        callers that do not rely on this module's .env. If omitted, uses
        ABRA_DATABASE_URL, else PG_* vars."""
        self.writer_uri = writer_uri or default_writer_uri()
        self.conn = db.connect(dsn or None)
        self.dialect = db.dialect(dsn or None)

    def store_content(self, source_file, content, note_date=None, catcode=None,
                      embedding=None):
        """Store a content blob. Returns content ID.
        Populates both `catcode` (singular, legacy) and `catcodes` (array, current spec).
        Stamps created_by from self.writer_uri.
        An embedding (list of floats) is generated when one is not supplied: rows
        with a NULL embedding are excluded from the vector query, so an unembedded
        blob is reachable only by name, never by search."""
        if embedding is None:
            embedding = embed(content)
        cur = self.conn.cursor()
        catcodes = [catcode] if catcode else []
        cur.execute(
            "INSERT INTO content (source_file, content, note_date, catcode, catcodes, created_by, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (source_file, content, note_date, catcode, self.dialect.array(catcodes),
             self.writer_uri, self.dialect.vector(embedding))
        )
        content_id = cur.fetchone()[0]
        self.conn.commit()
        cur.close()
        return content_id

    def write_binding(self, scope, name, rel=None, target_type=None, target_ref=None,
                      qualifier=None, permanence="CURRENT", source_date=None, catcode=None,
                      relationship=None):
        """Write a single binding. Rejects PII in target_ref.
        Accepts the relationship as `rel` or `relationship`.
        Populates both `catcode` (legacy) and `catcodes` (array, current spec).
        Stamps created_by from self.writer_uri."""
        relationship = rel or relationship
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
             qualifier, permanence, source_date, catcode, self.dialect.array(catcodes),
             self.writer_uri)
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
        d = self.dialect
        cur.execute(
            f"""INSERT INTO hot_tags (scope, name, priority, expires_at)
               VALUES (%s, %s, %s, {d.now_plus_days()})
               ON CONFLICT (scope, name) DO UPDATE SET
                   priority = EXCLUDED.priority,
                   expires_at = EXCLUDED.expires_at,
                   added_at = {d.now}""",
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

    def set_label(self, scope, name, label, expires_at=None):
        """Upsert a label on a name (migration 003). Multiple labels per
        (scope, name) allowed. `added_by` is stamped from self.writer_uri
        for provenance."""
        label = (label or "").strip()
        if not label:
            raise ValueError("label must be a non-empty string")
        cur = self.conn.cursor()
        cur.execute(
            f"""INSERT INTO labels (scope, name, label, added_by, expires_at)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (scope, name, label) DO UPDATE SET
                   added_by = EXCLUDED.added_by,
                   added_at = {self.dialect.now},
                   expires_at = EXCLUDED.expires_at""",
            (scope, name, label, self.writer_uri, expires_at)
        )
        self.conn.commit()
        cur.close()

    def remove_label(self, scope, name, label):
        """Remove a label from a name."""
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM labels WHERE scope = %s AND name = %s AND label = %s",
            (scope, name, (label or "").strip())
        )
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

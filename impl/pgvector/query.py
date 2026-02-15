#!/usr/bin/env python3
"""
Query abra bindings and content.

Usage:
    # Who do I know? (search names and qualifiers)
    .venv/bin/python pgvector/query.py who credentials
    .venv/bin/python pgvector/query.py who "workforce dev"

    # What do I know about someone?
    .venv/bin/python pgvector/query.py about bobbi-vernon
    .venv/bin/python pgvector/query.py about eric

    # Who did I meet in a time range?
    .venv/bin/python pgvector/query.py when 2025-10
    .venv/bin/python pgvector/query.py when 2025-07 2025-08

    # Search note content
    .venv/bin/python pgvector/query.py search "cooperative"
    .venv/bin/python pgvector/query.py search "donor advised"

    # Who is related to a name/topic?
    .venv/bin/python pgvector/query.py related linkedtrust
    .venv/bin/python pgvector/query.py related skillsaware

    # List all LT reference docs
    .venv/bin/python pgvector/query.py refs

    # Dump all names (with optional prefix filter)
    .venv/bin/python pgvector/query.py names
    .venv/bin/python pgvector/query.py names eric
"""
import os
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


def get_conn():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname=PG_DATABASE
    )


def cmd_who(args):
    """Find people by topic/qualifier keyword."""
    term = args.term
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT b.name, b.qualifier, b.source_date
        FROM bindings b
        WHERE b.scope = %s
        AND b.relationship = 'ABOUT'
        AND b.qualifier ILIKE %s
        ORDER BY b.name
    """, (args.scope, f"%{term}%"))
    rows = cur.fetchall()
    if not rows:
        # Also try content search as fallback
        cur.execute("""
            SELECT DISTINCT b.name, b.qualifier, b.source_date
            FROM bindings b
            JOIN content c ON c.id = CAST(b.target_ref AS INTEGER)
            WHERE b.scope = %s
            AND b.relationship = 'ABOUT'
            AND b.target_type = 'content'
            AND c.content ILIKE %s
            ORDER BY b.name
        """, (args.scope, f"%{term}%"))
        rows = cur.fetchall()
        if rows:
            print(f"(matched in note content)")
    if not rows:
        print(f"No contacts found for '{term}'")
    else:
        print(f"Contacts related to '{term}':\n")
        for name, qual, date in rows:
            d = f" ({date})" if date else ""
            print(f"  {name}: {qual}{d}")
    cur.close()
    conn.close()


def cmd_about(args):
    """Show everything known about a name."""
    name = args.name
    conn = get_conn()
    cur = conn.cursor()
    # Find matching names
    cur.execute("""
        SELECT DISTINCT name FROM bindings
        WHERE scope = %s AND name ILIKE %s
        ORDER BY name
    """, (args.scope, f"%{name}%"))
    names = [r[0] for r in cur.fetchall()]
    if not names:
        print(f"No names matching '{name}'")
        cur.close()
        conn.close()
        return

    for n in names:
        print(f"=== {n} ===")
        cur.execute("""
            SELECT relationship, target_type, target_ref, qualifier, source_date
            FROM bindings
            WHERE scope = %s AND name = %s
            ORDER BY relationship, source_date
        """, (args.scope, n))
        for rel, ttype, tref, qual, date in cur.fetchall():
            d = f" ({date})" if date else ""
            q = f" [{qual}]" if qual else ""
            if rel == 'ABOUT' and ttype == 'content':
                # Fetch content snippet
                try:
                    cur2 = conn.cursor()
                    cur2.execute("SELECT source_file, LEFT(content, 200) FROM content WHERE id = %s", (int(tref),))
                    row = cur2.fetchone()
                    cur2.close()
                    if row:
                        print(f"  {rel}{q}{d}")
                        print(f"    source: {row[0]}")
                        print(f"    {row[1][:150]}...")
                        continue
                except (ValueError, TypeError):
                    pass
            print(f"  {rel} [{ttype}] {tref[:80]}{q}{d}")
        print()
    cur.close()
    conn.close()


def cmd_when(args):
    """Find contacts by date range."""
    start = args.start
    # If just a month like "2025-10", expand
    if len(start) == 7:
        start_date = start + "-01"
        if args.end:
            end_date = args.end + "-01" if len(args.end) == 7 else args.end
        else:
            # Next month
            y, m = int(start[:4]), int(start[5:7])
            m += 1
            if m > 12:
                m = 1
                y += 1
            end_date = f"{y}-{m:02d}-01"
    else:
        start_date = start
        end_date = args.end or "2099-12-31"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT b.name, b.qualifier, b.source_date
        FROM bindings b
        WHERE b.scope = %s
        AND b.relationship = 'ABOUT'
        AND b.source_date >= %s AND b.source_date < %s
        ORDER BY b.source_date, b.name
    """, (args.scope, start_date, end_date))
    rows = cur.fetchall()
    if not rows:
        print(f"No contacts found for {start_date} to {end_date}")
    else:
        print(f"Contacts from {start_date} to {end_date}:\n")
        for name, qual, date in rows:
            print(f"  {date}: {name} — {qual}")
    cur.close()
    conn.close()


def cmd_search(args):
    """Search note content."""
    term = args.term
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.source_file, c.note_date, c.content
        FROM content c
        WHERE c.content ILIKE %s
        ORDER BY c.note_date
    """, (f"%{term}%",))
    rows = cur.fetchall()
    if not rows:
        print(f"No notes matching '{term}'")
    else:
        print(f"Notes matching '{term}':\n")
        for cid, src, date, content in rows:
            print(f"  [{cid}] {src} ({date})")
            # Show up to 5 matching lines
            matches = []
            for line in content.split('\n'):
                if term.lower() in line.lower():
                    matches.append(line.strip())
                    if len(matches) >= 5:
                        break
            for m in matches:
                print(f"    > {m}")
            if not matches:
                print(f"    (match in content)")
            print()
    cur.close()
    conn.close()


def cmd_related(args):
    """Find who is related to a name or topic."""
    target = args.target
    conn = get_conn()
    cur = conn.cursor()
    # RELATED bindings where target_ref matches
    cur.execute("""
        SELECT b.name, b.qualifier, b.source_date
        FROM bindings b
        WHERE b.scope = %s
        AND b.relationship = 'RELATED'
        AND (b.target_ref ILIKE %s OR b.qualifier ILIKE %s)
        ORDER BY b.name
    """, (args.scope, f"%{target}%", f"%{target}%"))
    rows = cur.fetchall()
    if not rows:
        print(f"No RELATED bindings matching '{target}'")
    else:
        print(f"Related to '{target}':\n")
        for name, qual, date in rows:
            d = f" ({date})" if date else ""
            print(f"  {name}: {qual}{d}")
    cur.close()
    conn.close()


def cmd_refs(args):
    """List all LinkedTrust reference docs."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.name, b.qualifier, b.source_date
        FROM bindings b
        WHERE b.scope = 'linkedtrust'
        AND b.relationship = 'ABOUT'
        ORDER BY b.source_date NULLS LAST
    """)
    rows = cur.fetchall()
    if not rows:
        print("No LT reference docs found")
    else:
        print("LinkedTrust reference docs:\n")
        for name, qual, date in rows:
            d = f" ({date})" if date else ""
            print(f"  {name}: {qual}{d}")
    cur.close()
    conn.close()


def cmd_names(args):
    """List names that have context (ABOUT or RELATED bindings)."""
    prefix = args.prefix or ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT b.name, b.qualifier, b.source_date
        FROM bindings b
        WHERE b.scope = %s AND b.name ILIKE %s
        AND b.relationship IN ('ABOUT', 'RELATED')
        ORDER BY b.name
    """, (args.scope, f"{prefix}%"))
    rows = cur.fetchall()
    if not rows:
        print(f"No names matching '{prefix}*'")
    else:
        # Group by name, show first qualifier
        seen = {}
        for name, qual, date in rows:
            if name not in seen:
                seen[name] = (qual, date)
        print(f"{len(seen)} names:\n")
        for name, (qual, date) in seen.items():
            d = f" ({date})" if date else ""
            print(f"  {name}: {qual}{d}")
    cur.close()
    conn.close()


def cmd_read(args):
    """Read the full content linked to a name or content ID."""
    target = args.target
    conn = get_conn()
    cur = conn.cursor()
    # Try as content ID first
    try:
        cid = int(target)
        cur.execute("SELECT source_file, note_date, content FROM content WHERE id = %s", (cid,))
        row = cur.fetchone()
        if row:
            print(f"[{cid}] {row[0]} ({row[1]})\n")
            print(row[2])
            cur.close()
            conn.close()
            return
    except ValueError:
        pass
    # Find by name — get all ABOUT content bindings
    cur.execute("""
        SELECT c.id, c.source_file, c.note_date, c.content
        FROM bindings b
        JOIN content c ON c.id = CAST(b.target_ref AS INTEGER)
        WHERE b.name ILIKE %s
        AND b.relationship = 'ABOUT'
        AND b.target_type = 'content'
        ORDER BY c.note_date
    """, (f"%{target}%",))
    rows = cur.fetchall()
    if not rows:
        # Try linkedtrust scope too
        cur.execute("""
            SELECT c.id, c.source_file, c.note_date, c.content
            FROM bindings b
            JOIN content c ON c.id = CAST(b.target_ref AS INTEGER)
            WHERE b.scope = 'linkedtrust'
            AND b.name ILIKE %s
            AND b.relationship = 'ABOUT'
            AND b.target_type = 'content'
            ORDER BY c.note_date
        """, (f"%{target}%",))
        rows = cur.fetchall()
    if not rows:
        print(f"No content found for '{target}'")
    else:
        for cid, src, date, content in rows:
            print(f"[{cid}] {src} ({date})")
            print("-" * 40)
            print(content)
            print()
    cur.close()
    conn.close()


HELP_TEXT = """
abra — query your contacts, notes, and relationships

Commands:
  abra who "credentials"         Find people by topic keyword
  abra about bobbi-vernon        Everything known about a person
  abra about eric                Partial match works too
  abra when 2025-10              Who did I meet that month?
  abra when 2025-07 2025-09      Date range (July thru August)
  abra search "cooperative"      Full-text search across all notes
  abra related linkedtrust       Who has a relationship to X?
  abra refs                      List all LinkedTrust reference docs
  abra names                     List all processed names (with context)
  abra names kevin               Filter names by prefix
  abra read bobbi-vernon         Read full note content for a name
  abra read 35                   Read content by ID number

Options:
  --scope SCOPE                  Query a different scope (default: golda)

For complex queries, ask Claude in a session:
  "use the abra tool to find everyone in healthcare credentialing"
  "query abra for contacts I should follow up with from badge conferences"
""".strip()


def main():
    # Show help if no args or just --help
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print(HELP_TEXT)
        sys.exit(0)

    # Check for unknown command before argparse to give a friendly message
    valid_commands = {'who', 'about', 'when', 'search', 'related', 'refs', 'names', 'read'}
    first_arg = sys.argv[1]
    if first_arg not in valid_commands and not first_arg.startswith('-'):
        print(f"Unknown command: '{first_arg}'\n")
        print(HELP_TEXT)
        sys.exit(1)

    parser = argparse.ArgumentParser(description='abra — query contacts, notes, and relationships',
                                     add_help=False)
    parser.add_argument('--scope', default='golda', help='Scope to query (default: golda)')
    sub = parser.add_subparsers(dest='command')

    p_who = sub.add_parser('who', help='Find people by topic')
    p_who.add_argument('term', help='Topic keyword to search')

    p_about = sub.add_parser('about', help='Show everything about a name')
    p_about.add_argument('name', help='Name or prefix to look up')

    p_when = sub.add_parser('when', help='Find contacts by date')
    p_when.add_argument('start', help='Start date (YYYY-MM or YYYY-MM-DD)')
    p_when.add_argument('end', nargs='?', help='End date (optional)')

    p_search = sub.add_parser('search', help='Search note content')
    p_search.add_argument('term', help='Text to search for')

    p_related = sub.add_parser('related', help='Find related contacts')
    p_related.add_argument('target', help='Name or topic to find relations for')

    p_refs = sub.add_parser('refs', help='List LT reference docs')

    p_names = sub.add_parser('names', help='List known names')
    p_names.add_argument('prefix', nargs='?', help='Filter by prefix')

    p_read = sub.add_parser('read', help='Read full note content')
    p_read.add_argument('target', help='Name or content ID')

    args = parser.parse_args()
    if not args.command:
        print(HELP_TEXT)
        sys.exit(0)

    cmds = {
        'who': cmd_who, 'about': cmd_about, 'when': cmd_when,
        'search': cmd_search, 'related': cmd_related, 'refs': cmd_refs,
        'names': cmd_names, 'read': cmd_read,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()

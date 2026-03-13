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

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
_model = None


def get_model():
    """Lazy-load embedding model (only when needed for vector search)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model

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
    """Show everything known about a name. Hot tags shown first."""
    name = args.name
    conn = get_conn()
    cur = conn.cursor()

    # Check both scopes for hot tags
    scopes_to_check = [args.scope]
    if args.scope == 'golda':
        scopes_to_check.append('linkedtrust')
    elif args.scope == 'linkedtrust':
        scopes_to_check.append('golda')

    # Check if this name is hot in any scope — show hot content first
    for sc in scopes_to_check:
        cur.execute("SELECT 1 FROM hot_tags WHERE scope = %s AND name = %s", (sc, name))
        if cur.fetchone():
            # Show hot tag content prominently
            cur.execute("""
                SELECT c.id, c.content
                FROM bindings b
                JOIN content c ON c.id = CAST(b.target_ref AS INTEGER)
                WHERE b.scope = %s AND b.name = %s
                AND b.relationship = 'ABOUT' AND b.target_type = 'content'
                AND b.qualifier = 'hot tag definition'
                ORDER BY c.id DESC LIMIT 1
            """, (sc, name))
            hot_row = cur.fetchone()
            if hot_row:
                print(f"=== {name} [HOT] ===\n")
                print(hot_row[1])
                print()
                # Still show other bindings below
                break

    # Find matching names
    cur.execute("""
        SELECT DISTINCT name FROM bindings
        WHERE scope = %s AND name ILIKE %s
        ORDER BY name
    """, (args.scope, f"%{name}%"))
    names = [r[0] for r in cur.fetchall()]
    if not names:
        # Try linkedtrust scope too
        if args.scope != 'linkedtrust':
            cur.execute("""
                SELECT DISTINCT name FROM bindings
                WHERE scope = 'linkedtrust' AND name ILIKE %s
                ORDER BY name
            """, (f"%{name}%",))
            names = [r[0] for r in cur.fetchall()]
            if names:
                print(f"(found in linkedtrust scope)")
                args.scope = 'linkedtrust'
        if not names:
            print(f"No names matching '{name}'")
            cur.close()
            conn.close()
            return

    for n in names:
        # Check hot status
        cur.execute("SELECT 1 FROM hot_tags WHERE scope = %s AND name = %s", (args.scope, n))
        is_hot = cur.fetchone()
        marker = " [HOT]" if is_hot else ""
        print(f"=== {n}{marker} ===")
        cur.execute("""
            SELECT relationship, target_type, target_ref, qualifier, source_date
            FROM bindings
            WHERE scope = %s AND name = %s
            ORDER BY relationship, source_date
        """, (args.scope, n))
        for rel, ttype, tref, qual, date in cur.fetchall():
            # Skip hot tag definition in the bindings list — already shown above
            if qual == 'hot tag definition':
                continue
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
    """Search note content using vector similarity, falling back to ILIKE."""
    term = args.term
    limit = getattr(args, 'limit', 20)
    conn = get_conn()
    cur = conn.cursor()

    # Check if any embeddings exist
    cur.execute("SELECT EXISTS(SELECT 1 FROM content WHERE embedding IS NOT NULL)")
    has_embeddings = cur.fetchone()[0]

    if has_embeddings:
        # Vector similarity search with associated names
        model = get_model()
        query_vec = model.encode(term).tolist()
        cur.execute("""
            SELECT c.id, c.source_file, c.note_date, c.content,
                   1 - (c.embedding <=> %s::vector) AS similarity
            FROM content c
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
        """, (query_vec, query_vec, limit))
        rows = cur.fetchall()
        if rows:
            # Batch-fetch associated names + display names for all content IDs
            cids = [str(r[0]) for r in rows]
            cur.execute("""
                SELECT ab.target_ref, ab.name,
                       (SELECT isb.target_ref FROM bindings isb
                        WHERE isb.name = ab.name AND isb.scope = ab.scope
                        AND isb.relationship = 'IS' LIMIT 1)
                FROM bindings ab
                WHERE ab.target_type = 'content'
                AND ab.relationship = 'ABOUT'
                AND ab.target_ref = ANY(%s)
            """, (cids,))
            content_names = {}
            for tref, slug, display in cur.fetchall():
                label = display or slug
                content_names.setdefault(tref, []).append(label)

            print(f"Notes matching '{term}' (semantic search):\n")
            for cid, src, date, content, sim in rows:
                score = f"{sim:.3f}"
                names = content_names.get(str(cid), [])
                name_str = f"  names: {', '.join(sorted(set(names)))}" if names else ""
                print(f"  [{cid}] {src} ({date}) score={score}")
                if name_str:
                    print(f"   {name_str}")
                # Show first meaningful line as preview
                for line in content.split('\n'):
                    line = line.strip()
                    if len(line) > 20:
                        print(f"    > {line[:150]}")
                        break
                print()
        else:
            print(f"No notes matching '{term}'")
    else:
        # Fallback: ILIKE text search (no embeddings populated)
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


def cmd_hot(args):
    """List hot tags or show a specific one."""
    name = getattr(args, 'name', None)
    conn = get_conn()
    cur = conn.cursor()

    if not name:
        # List all hot tags across both scopes (skip expired)
        cur.execute("""
            SELECT h.scope, h.name, h.priority, h.expires_at,
                   (SELECT b.target_ref FROM bindings b
                    WHERE b.scope = h.scope AND b.name = h.name
                    AND b.relationship = 'IS' LIMIT 1)
            FROM hot_tags h
            WHERE h.expires_at IS NULL OR h.expires_at > NOW()
            ORDER BY h.priority DESC, h.scope, h.name
        """)
        rows = cur.fetchall()
        if not rows:
            print("No hot tags")
        else:
            print(f"Hot tags:\n")
            for scope, name, pri, expires, is_text in rows:
                desc = f" — {is_text[:70]}" if is_text else ""
                exp = ""
                if expires:
                    days_left = (expires - __import__('datetime').datetime.now()).days
                    exp = f" (expires in {days_left}d)"
                print(f"  [{scope}] {name}{desc}{exp}")
    else:
        # Show specific hot tag — full definition content
        cur.execute("""
            SELECT h.scope FROM hot_tags h WHERE h.name = %s
            ORDER BY CASE WHEN h.scope = %s THEN 0 ELSE 1 END
            LIMIT 1
        """, (name, args.scope))
        row = cur.fetchone()
        if not row:
            print(f"'{name}' is not a hot tag")
            cur.close(); conn.close()
            return
        scope = row[0]

        # Fetch hot tag definition content
        cur.execute("""
            SELECT c.id, c.content
            FROM bindings b
            JOIN content c ON c.id = CAST(b.target_ref AS INTEGER)
            WHERE b.scope = %s AND b.name = %s
            AND b.relationship = 'ABOUT' AND b.target_type = 'content'
            AND b.qualifier = 'hot tag definition'
            ORDER BY c.id DESC LIMIT 1
        """, (scope, name))
        defn = cur.fetchone()
        if defn:
            print(f"=== {name} [HOT] ===\n")
            print(defn[1])
        else:
            # No definition blob, show IS text at least
            cur.execute("""
                SELECT target_ref FROM bindings
                WHERE scope = %s AND name = %s AND relationship = 'IS'
                LIMIT 1
            """, (scope, name))
            is_row = cur.fetchone()
            if is_row:
                print(f"=== {name} [HOT] ===\n{is_row[0]}")
                print("\n(no detailed definition — use 'abra about' for bindings)")
            else:
                print(f"'{name}' is hot but has no definition or IS binding")

    cur.close()
    conn.close()


def cmd_store(args):
    """Store a content blob and bind it to a name."""
    from write_binding import AbraWriter
    writer = AbraWriter()

    # Read content from file or argument
    if args.file:
        if not os.path.exists(args.file):
            print(f"File not found: {args.file}")
            sys.exit(1)
        with open(args.file) as f:
            content = f.read()
        source_file = os.path.basename(args.file)
    else:
        content = args.content
        source_file = f"cli-{args.name}"

    if not content:
        print("No content provided. Use 'abra store <name> \"text\"' or 'abra store <name> -f file.txt'")
        sys.exit(1)

    content_id = writer.store_content(source_file, content)
    qualifier = args.qualifier or "stored via cli"
    writer.write_binding(args.scope, args.name, "ABOUT", "content", str(content_id), qualifier=qualifier)
    print(f"Stored content [{content_id}] and bound to {args.name} [{qualifier}]")
    writer.close()


def cmd_bind(args):
    """Create a binding between a name and a target."""
    from write_binding import AbraWriter
    writer = AbraWriter()

    target_type = args.target_type or "text"
    bid = writer.write_binding(args.scope, args.name, args.rel, target_type,
                                args.target, qualifier=args.qualifier)
    if bid:
        q = f" [{args.qualifier}]" if args.qualifier else ""
        print(f"Created binding {bid}: {args.name} {args.rel} [{target_type}] {args.target}{q}")
    writer.close()


def cmd_hot_set(args):
    """Mark a name as hot (default 30 day expiry)."""
    from write_binding import AbraWriter
    writer = AbraWriter()
    days = args.days or 30
    writer.set_hot(args.scope, args.name, days=days)
    print(f"Set {args.name} as hot in [{args.scope}] — expires in {days} days")
    writer.close()


def cmd_hot_unset(args):
    """Remove a name from the hot list."""
    from write_binding import AbraWriter
    writer = AbraWriter()
    count = writer.unset_hot(args.scope, args.name)
    if count:
        print(f"Removed hot tag: {args.name}")
    else:
        print(f"'{args.name}' was not hot")
    writer.close()


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
abra — query and write contacts, notes, and relationships

Read commands:
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
  abra hot                       List all hot tags (warm context)
  abra hot alonovo               Show hot tag definition
  abra read bobbi-vernon         Read full note content for a name
  abra read 35                   Read content by ID number

Write commands:
  abra store <name> "text"       Store content and bind to a name
  abra store <name> -f file.txt  Store content from a file
  abra bind <name> IS "Full Name"              Create a binding
  abra bind <name> RELATED target --qualifier "context"
  abra hot set <name>            Mark as hot (expires in 30 days)
  abra hot set <name> --days 90  Custom expiry
  abra hot unset <name>          Remove hot tag

Options:
  --scope SCOPE                  Scope (default: golda)
  --qualifier TEXT               Qualifier for store/bind

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
    valid_commands = {'who', 'about', 'when', 'search', 'related', 'refs', 'names', 'read', 'hot', 'store', 'bind'}
    first_arg = sys.argv[1]
    if first_arg not in valid_commands and not first_arg.startswith('-'):
        print(f"Unknown command: '{first_arg}'\n")
        print(HELP_TEXT)
        sys.exit(1)

    parser = argparse.ArgumentParser(description='abra — query contacts, notes, and relationships',
                                     add_help=False)
    parser.add_argument('--scope', default='golda', help='Scope to query (default: golda)')
    sub = parser.add_subparsers(dest='command')

    scope_kw = dict(default=argparse.SUPPRESS, help='Scope to query')

    p_who = sub.add_parser('who', help='Find people by topic')
    p_who.add_argument('--scope', **scope_kw)
    p_who.add_argument('term', help='Topic keyword to search')

    p_about = sub.add_parser('about', help='Show everything about a name')
    p_about.add_argument('--scope', **scope_kw)
    p_about.add_argument('name', help='Name or prefix to look up')

    p_when = sub.add_parser('when', help='Find contacts by date')
    p_when.add_argument('--scope', **scope_kw)
    p_when.add_argument('start', help='Start date (YYYY-MM or YYYY-MM-DD)')
    p_when.add_argument('end', nargs='?', help='End date (optional)')

    p_search = sub.add_parser('search', help='Search note content')
    p_search.add_argument('term', help='Text to search for')

    p_related = sub.add_parser('related', help='Find related contacts')
    p_related.add_argument('--scope', **scope_kw)
    p_related.add_argument('target', help='Name or topic to find relations for')

    p_refs = sub.add_parser('refs', help='List LT reference docs')

    p_names = sub.add_parser('names', help='List known names')
    p_names.add_argument('--scope', **scope_kw)
    p_names.add_argument('prefix', nargs='?', help='Filter by prefix')

    p_hot = sub.add_parser('hot', help='List, show, set, or unset hot tags')
    p_hot.add_argument('--scope', **scope_kw)
    p_hot.add_argument('name', nargs='?', help='Hot tag name, or "set"/"unset"')
    p_hot.add_argument('name2', nargs='?', help='Name when using set/unset')
    p_hot.add_argument('--days', type=int, help='Expiry in days (default 30, for set)')

    p_read = sub.add_parser('read', help='Read full note content')
    p_read.add_argument('target', help='Name or content ID')

    p_store = sub.add_parser('store', help='Store content and bind to a name')
    p_store.add_argument('--scope', **scope_kw)
    p_store.add_argument('name', help='Name to bind content to')
    p_store.add_argument('content', nargs='?', help='Content text (or use -f)')
    p_store.add_argument('-f', '--file', help='Read content from file')
    p_store.add_argument('--qualifier', help='Qualifier for the ABOUT binding')

    p_bind = sub.add_parser('bind', help='Create a binding')
    p_bind.add_argument('--scope', **scope_kw)
    p_bind.add_argument('name', help='Name (subject)')
    p_bind.add_argument('rel', help='Relationship (IS, HAS, RELATED, ABOUT, etc)')
    p_bind.add_argument('target', help='Target value')
    p_bind.add_argument('--target-type', help='Target type: text, content, uri, name (default: text)')
    p_bind.add_argument('--qualifier', help='Qualifier text')

    args = parser.parse_args()
    if not args.command:
        print(HELP_TEXT)
        sys.exit(0)

    # Handle "hot set <name>" and "hot unset <name>" as sub-subcommands
    if args.command == 'hot' and args.name in ('set', 'unset'):
        if not args.name2:
            print(f"Usage: abra hot {args.name} <name>")
            sys.exit(1)
        args.name_actual = args.name  # 'set' or 'unset'
        args.name = args.name2
        if args.name_actual == 'set':
            cmd_hot_set(args)
        else:
            cmd_hot_unset(args)
        return

    cmds = {
        'who': cmd_who, 'about': cmd_about, 'when': cmd_when,
        'search': cmd_search, 'related': cmd_related, 'refs': cmd_refs,
        'names': cmd_names, 'read': cmd_read, 'hot': cmd_hot,
        'store': cmd_store, 'bind': cmd_bind,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()

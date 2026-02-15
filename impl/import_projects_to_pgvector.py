#!/usr/bin/env python3
"""
Import project MAIN.md files and Ideas into pgvector under linkedtrust/2026/ catcodes.

Usage:
    cd /opt/shared/repos/abra/impl

    # Dry run (default)
    .venv/bin/python import_projects_to_pgvector.py

    # Actually import
    .venv/bin/python import_projects_to_pgvector.py --confirm

    # Replace existing (deletes old content under linkedtrust/2026/projects and ideas)
    .venv/bin/python import_projects_to_pgvector.py --confirm --replace

    # Also load the LinkedClaims spec
    .venv/bin/python import_projects_to_pgvector.py --confirm --include-spec
"""
import os
import sys
import argparse
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'pgvector'))
from write_binding import AbraWriter

PROJECTS_DIR = "/opt/shared/projects/Active"
IDEAS_DIR = "/opt/shared/projects/Ideas"
LINKEDCLAIMS_SPEC = "/opt/shared/repos/LinkedClaims/spec.md"

# Catcode structure
CC_LT = "a00103"                  # linkedtrust
CC_2026 = "a0010302"              # linkedtrust/2026
CC_PROJECTS = "a001030201"        # linkedtrust/2026/projects
CC_IDEAS = "a001030202"           # linkedtrust/2026/ideas
CC_SPECS = "a001030203"           # linkedtrust/2026/specs


def load_project_files(projects_dir):
    """Load all MAIN.md files from Active projects. Returns list of (name, filepath, content)."""
    results = []
    for proj_dir in sorted(os.listdir(projects_dir)):
        proj_path = os.path.join(projects_dir, proj_dir)
        if not os.path.isdir(proj_path):
            continue
        # Load MAIN.md
        main_md = os.path.join(proj_path, "MAIN.md")
        if os.path.exists(main_md):
            with open(main_md) as f:
                content = f.read()
            results.append((proj_dir, main_md, content))
        else:
            # Check for any .md files
            md_files = glob.glob(os.path.join(proj_path, "*.md"))
            if md_files:
                # Use first .md file found
                with open(md_files[0]) as f:
                    content = f.read()
                results.append((proj_dir, md_files[0], content))
    return results


def load_extra_project_files(projects_dir):
    """Load additional .md files beyond MAIN.md for projects that have them."""
    results = []
    for proj_dir in sorted(os.listdir(projects_dir)):
        proj_path = os.path.join(projects_dir, proj_dir)
        if not os.path.isdir(proj_path):
            continue
        for md_file in sorted(glob.glob(os.path.join(proj_path, "*.md"))):
            basename = os.path.basename(md_file)
            if basename == "MAIN.md":
                continue
            with open(md_file) as f:
                content = f.read()
            results.append((proj_dir, basename, md_file, content))
    return results


def load_idea_files(ideas_dir):
    """Load idea markdown files. Returns list of (name, filepath, content)."""
    results = []
    for item in sorted(os.listdir(ideas_dir)):
        path = os.path.join(ideas_dir, item)
        if item in ("README.md", "index.md"):
            continue
        if item.endswith(".md") and os.path.isfile(path):
            name = item.replace(".md", "")
            with open(path) as f:
                content = f.read()
            results.append((name, path, content))
        elif os.path.isdir(path):
            # Check for MAIN.md or any .md inside
            main_md = os.path.join(path, "MAIN.md")
            if os.path.exists(main_md):
                with open(main_md) as f:
                    content = f.read()
                results.append((item, main_md, content))
            else:
                md_files = glob.glob(os.path.join(path, "*.md"))
                if md_files:
                    with open(md_files[0]) as f:
                        content = f.read()
                    results.append((item, md_files[0], content))
    return results


def extract_summary(content, max_lines=3):
    """Extract a short summary from markdown content (first meaningful paragraph)."""
    lines = content.split('\n')
    summary_lines = []
    in_header = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if summary_lines and not in_header:
                break
            continue
        if stripped.startswith('#'):
            in_header = True
            continue
        if stripped.startswith('---') or stripped.startswith('```'):
            continue
        in_header = False
        summary_lines.append(stripped)
        if len(summary_lines) >= max_lines:
            break
    return ' '.join(summary_lines)[:250]


def main():
    parser = argparse.ArgumentParser(description="Import projects and ideas to pgvector")
    parser.add_argument("--confirm", action="store_true", help="Actually write (default is dry run)")
    parser.add_argument("--replace", action="store_true", help="Delete existing project/idea content first")
    parser.add_argument("--include-spec", action="store_true", help="Also load LinkedClaims spec.md")
    args = parser.parse_args()

    # Load data
    projects = load_project_files(PROJECTS_DIR)
    extras = load_extra_project_files(PROJECTS_DIR)
    ideas = load_idea_files(IDEAS_DIR)

    print(f"Active projects: {len(projects)}")
    for name, path, content in projects:
        summary = extract_summary(content)
        print(f"  {name}: {summary[:80]}...")

    if extras:
        print(f"\nExtra project files: {len(extras)}")
        for proj, basename, path, content in extras:
            print(f"  {proj}/{basename} ({len(content)} chars)")

    print(f"\nIdeas: {len(ideas)}")
    for name, path, content in ideas:
        summary = extract_summary(content)
        print(f"  {name}: {summary[:80]}...")

    if args.include_spec:
        if os.path.exists(LINKEDCLAIMS_SPEC):
            with open(LINKEDCLAIMS_SPEC) as f:
                spec_content = f.read()
            print(f"\nLinkedClaims spec: {len(spec_content)} chars")
        else:
            print(f"\nWARNING: spec not found at {LINKEDCLAIMS_SPEC}")
            spec_content = None
    else:
        spec_content = None

    if not args.confirm:
        print("\nDry run. Run with --confirm to write.")
        return

    writer = AbraWriter()

    # Register catcodes
    writer.register_catcode(CC_2026, CC_LT, "linkedtrust/2026")
    writer.register_catcode(CC_PROJECTS, CC_2026, "linkedtrust/2026/projects")
    writer.register_catcode(CC_IDEAS, CC_2026, "linkedtrust/2026/ideas")
    if spec_content:
        writer.register_catcode(CC_SPECS, CC_2026, "linkedtrust/2026/specs")
    print("Catcodes registered.")

    # Delete old if replacing
    if args.replace:
        cur = writer.conn.cursor()
        cur.execute("DELETE FROM content WHERE catcode LIKE %s", (f"{CC_PROJECTS}%",))
        p_content = cur.rowcount
        cur.execute("DELETE FROM bindings WHERE catcode LIKE %s", (f"{CC_PROJECTS}%",))
        p_bindings = cur.rowcount
        cur.execute("DELETE FROM content WHERE catcode LIKE %s", (f"{CC_IDEAS}%",))
        i_content = cur.rowcount
        cur.execute("DELETE FROM bindings WHERE catcode LIKE %s", (f"{CC_IDEAS}%",))
        i_bindings = cur.rowcount
        if spec_content:
            cur.execute("DELETE FROM content WHERE catcode LIKE %s", (f"{CC_SPECS}%",))
            s_content = cur.rowcount
            cur.execute("DELETE FROM bindings WHERE catcode LIKE %s", (f"{CC_SPECS}%",))
            s_bindings = cur.rowcount
        else:
            s_content = s_bindings = 0
        writer.conn.commit()
        cur.close()
        print(f"Replaced: deleted {p_content + i_content + s_content} content, {p_bindings + i_bindings + s_bindings} bindings")

    # Store projects
    print("\nLoading projects...")
    for name, path, content in projects:
        summary = extract_summary(content)
        source_file = f"projects/Active/{name}/MAIN.md"
        cid = writer.store_content(source_file, content, note_date="2026-02-15", catcode=CC_PROJECTS)

        # Binding: project name IS description
        writer.write_binding("linkedtrust", name, "IS", "text",
            summary[:250], permanence="CURRENT", source_date="2026-02-15", catcode=CC_PROJECTS)
        # Binding: project ABOUT content
        writer.write_binding("linkedtrust", name, "ABOUT", "content",
            str(cid), qualifier="project description",
            source_date="2026-02-15", catcode=CC_PROJECTS)
        print(f"  {name} -> content {cid}")

    # Store extra project files
    if extras:
        print("\nLoading extra project files...")
        for proj, basename, path, content in extras:
            source_file = f"projects/Active/{proj}/{basename}"
            label = basename.replace(".md", "").replace("-", " ")
            cid = writer.store_content(source_file, content, note_date="2026-02-15", catcode=CC_PROJECTS)
            writer.write_binding("linkedtrust", proj, "ABOUT", "content",
                str(cid), qualifier=label,
                source_date="2026-02-15", catcode=CC_PROJECTS)
            print(f"  {proj}/{basename} -> content {cid}")

    # Store ideas
    print("\nLoading ideas...")
    for name, path, content in ideas:
        summary = extract_summary(content)
        rel_path = os.path.relpath(path, "/opt/shared/projects")
        cid = writer.store_content(rel_path, content, note_date="2026-02-15", catcode=CC_IDEAS)

        writer.write_binding("linkedtrust", name, "IS", "text",
            summary[:250], permanence="CURRENT", source_date="2026-02-15", catcode=CC_IDEAS)
        writer.write_binding("linkedtrust", name, "ABOUT", "content",
            str(cid), qualifier="idea description",
            source_date="2026-02-15", catcode=CC_IDEAS)
        print(f"  {name} -> content {cid}")

    # Store LinkedClaims spec
    if spec_content:
        print("\nLoading LinkedClaims spec...")
        cid = writer.store_content("LinkedClaims/spec.md", spec_content,
            note_date="2026-02-15", catcode=CC_SPECS)
        writer.write_binding("linkedtrust", "linkedclaims", "ABOUT", "content",
            str(cid), qualifier="LinkedClaims specification (draft)",
            source_date="2026-02-15", catcode=CC_SPECS)
        print(f"  linkedclaims spec -> content {cid}")

    writer.close()
    total = len(projects) + len(extras) + len(ideas) + (1 if spec_content else 0)
    print(f"\nDone. {total} items loaded.")
    print(f"Query with: abra search \"streetwell\"")
    print(f"            abra related linkedtrust")
    print(f"            abra read <project-name>")


if __name__ == "__main__":
    main()

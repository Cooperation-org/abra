"""SQLite backend: dialect helpers, scope resolution, and the CLI end to end.

Run: impl/.venv/bin/python -m pytest impl/pgvector/tests
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

PGVECTOR = Path(__file__).resolve().parent.parent
IMPL = PGVECTOR.parent
sys.path.insert(0, str(PGVECTOR))

import db  # noqa: E402
import instance  # noqa: E402
import sources  # noqa: E402


@pytest.mark.parametrize("sql, expected", (
    ("SELECT 1 WHERE a = %s", "SELECT 1 WHERE a = ?"),
    ("a = %s AND b LIKE %s", "a = ? AND b LIKE ?"),
    ("x LIKE 'p%%' AND y = %s", "x LIKE 'p%' AND y = ?"),
    ("no params", "no params"),
))
def test_to_qmark(sql, expected):
    assert db._to_qmark(sql) == expected


@pytest.mark.parametrize("url, expected", (
    ("sqlite:///abra.db", Path("abra.db")),
    ("sqlite:////var/abra.db", Path("/var/abra.db")),
    ("sqlite:///~/.abra/abra.db", Path.home() / ".abra" / "abra.db"),
))
def test_sqlite_path(url, expected):
    assert db.is_sqlite(url)
    assert db.sqlite_path(url) == expected


@pytest.mark.parametrize("url, dialect", (
    ("sqlite:///x.db", db.SQLITE),
    ("postgresql://u@h/abra", db.POSTGRES),
    ("", db.POSTGRES),
))
def test_dialect_selection(url, dialect):
    assert db.dialect(url) is dialect


@pytest.mark.parametrize("env_scope, yaml_text, expected", (
    ("from-env", "scope: from-yaml\n", "from-env"),
    (None, "scope: from-yaml\n", "from-yaml"),
    (None, "schemes: {}\n", instance.calling_user()),
    (None, None, instance.calling_user()),
))
def test_default_scope(tmp_path, monkeypatch, env_scope, yaml_text, expected):
    sources_file = tmp_path / "sources.yaml"
    if yaml_text is not None:
        sources_file.write_text(yaml_text)
    monkeypatch.setenv("ABRA_SOURCES_FILE", str(sources_file))
    if env_scope:
        monkeypatch.setenv("ABRA_SCOPE", env_scope)
    else:
        monkeypatch.delenv("ABRA_SCOPE", raising=False)
    sources.reset_cache()
    assert instance.default_scope() == expected
    sources.reset_cache()


def test_connect_refuses_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        db.connect(f"sqlite:///{tmp_path}/missing.db")


def test_nearest_content_orders_by_cosine(tmp_path):
    url = f"sqlite:///{tmp_path}/v.db"
    conn = db.connect(url, create=True)
    conn.execute("CREATE TABLE content (id INTEGER PRIMARY KEY, source_file TEXT, "
                 "note_date DATE, content TEXT, embedding BLOB)")
    cur = conn.cursor()
    for cid, vec in ((1, [1, 0, 0]), (2, [0, 1, 0]), (3, [0.9, 0.1, 0]), (4, None)):
        cur.execute("INSERT INTO content (id, source_file, content, embedding) VALUES (%s, %s, %s, %s)",
                    (cid, f"f{cid}", f"c{cid}", db.SQLITE.vector(vec)))
    rows = db.SQLITE.nearest_content(cur, [1, 0, 0], 2)
    assert [r[0] for r in rows] == [1, 3]
    assert rows[0][4] == pytest.approx(1.0)
    conn.close()


def test_hot_tags_mirror_into_labels(tmp_path):
    from setup_db import SQLITE_SCHEMA
    from write_binding import AbraWriter
    url = f"sqlite:///{tmp_path}/h.db"
    conn = db.connect(url, create=True)
    conn.executescript(SQLITE_SCHEMA)
    conn.close()
    writer = AbraWriter(writer_uri="urn:abra:test", dsn=url)
    cur = writer.conn.cursor()
    label_rows = "SELECT scope, name, label, added_by FROM labels"
    for action, expected in (
        (lambda: writer.set_hot("s", "n", days=5), [("s", "n", "hot", "urn:abra:hot-tag-bridge")]),
        (lambda: writer.set_hot("s", "n", days=9), [("s", "n", "hot", "urn:abra:hot-tag-bridge")]),
        (lambda: writer.unset_hot("s", "n"), []),
    ):
        action()
        cur.execute(label_rows)
        assert cur.fetchall() == expected
    writer.close()


@pytest.fixture
def cli(tmp_path):
    """Run the abra wrapper against a fresh SQLite store."""
    env = {**os.environ,
           "ABRA_DATABASE_URL": f"sqlite:///{tmp_path}/abra.db",
           "ABRA_SOURCES_FILE": str(tmp_path / "none.yaml"),
           "ABRA_SCOPE": "test-scope",
           "ABRA_WRITER_URI": "urn:abra:test"}
    subprocess.run([str(IMPL / ".venv/bin/python"), str(PGVECTOR / "setup_db.py")],
                   env=env, check=True, capture_output=True)
    conn = db.connect(env["ABRA_DATABASE_URL"])
    conn.execute("INSERT INTO catcode_registry (catcode, parent_catcode, label) VALUES ('a0', NULL, 'root')")
    conn.commit()
    conn.close()

    def run(*args):
        r = subprocess.run([str(IMPL / "abra"), *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout

    run.url = env["ABRA_DATABASE_URL"]
    return run


def test_cli_round_trip(cli):
    steps = (
        (("bind", "ltq1", "IS", "the Q1 plan", "--cat", "root/plans"),
         "Created binding 1: ltq1 IS [text] the Q1 plan"),
        (("store", "ltq1", "Budget review for the cooperative grant", "--cat", "root/plans",
          "--qualifier", "planning notes", "--date", "2026-01-20"),
         "Stored content [1] and bound to ltq1 [planning notes]"),
        (("about", "ltq1"), "=== ltq1 ==="),
        (("about", "LTQ"), "IS [text] the Q1 plan"),
        (("names", "lt"), "ltq1: planning notes"),
        (("who", "planning"), "ltq1: planning notes"),
        (("when", "2026-01"), "2026-01-20: ltq1"),
        (("refs",), "ltq1: planning notes (2026-01-20)"),
        (("read", "ltq1"), "Budget review for the cooperative grant"),
        (("search", "grant money for a co-op"), "names: the Q1 plan"),
        (("hot", "set", "ltq1"), "Set ltq1 as hot in [test-scope]"),
        (("hot",), "[test-scope] ltq1 — the Q1 plan (expires in 29d)"),
        (("about", "ltq1"), "=== ltq1 [HOT] ==="),
        (("hot", "unset", "ltq1"), "Removed hot tag: ltq1"),
        (("hot",), "No hot tags"),
        (("about", "ltq1", "--scope", "other"), "No names matching 'ltq1' in scope 'other'"),
        (("reindex",), "Nothing to reindex"),
    )
    for args, expected in steps:
        assert expected in cli(*args), args

    conn = db.connect(cli.url)
    cur = conn.cursor()
    cur.execute("SELECT scope, created_by, catcodes FROM bindings ORDER BY id")
    assert cur.fetchall() == [("test-scope", "urn:abra:test", '["a001"]')] * 2
    cur.execute("SELECT label FROM catcode_registry WHERE catcode = 'a001'")
    assert cur.fetchone() == ("root/plans",)
    cur.execute("SELECT count(*) FROM labels WHERE label = 'hot'")
    assert cur.fetchone() == (0,)
    conn.close()

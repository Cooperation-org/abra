"""
Abra — pet names, catcodes, structured knowledge bindings.

Usage:
    from abra import AbraStore

    # Default (raw psycopg2, no multi-tenancy)
    store = AbraStore(dsn="postgresql://user:pass@host/abra")

    # With dependency injection (connection pool, embeddings, tenancy)
    store = AbraStore(
        get_conn=my_pool.get_connection,
        put_conn=my_pool.return_connection,
        embed_fn=my_embed_text,
        org_id=5,
        table_prefix="abra_",
    )

    # Query
    bindings = store.bindings_for("leanne-ussher")
    results = store.search_content("cooperative governance")
    hot = store.hot_tags()

    # Write
    store.write_binding("golda", "peter", "IS", "text", "Peter Smith")
    cid = store.store_content("notes/meeting.md", "scrubbed text...")

    # Override behavior by subclassing
    class MyStore(AbraStore):
        def rank_results(self, results, query):
            # custom boosting logic
            ...
"""

from abra.store import AbraStore
from abra.types import Binding, Content, HotTag, CatcodeEntry
from abra.pii import check_pii, PiiChecker

__version__ = "0.1.0"

__all__ = [
    "AbraStore",
    "Binding", "Content", "HotTag", "CatcodeEntry",
    "check_pii", "PiiChecker",
]

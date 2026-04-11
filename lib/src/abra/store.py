"""
AbraStore — the core read/write API for abra bindings.

Designed for injection and override:
- Connection management: inject get_conn/put_conn, or pass a dsn
- Embeddings: inject embed_fn for vector search
- Multi-tenancy: set org_id to filter all queries
- Table names: set table_prefix for local tables (e.g., "abra_")
- Search ranking: override rank_results() for custom boosting
- PII checking: inject a PiiChecker subclass

Default behavior (no injection) matches abra's own pgvector impl:
raw psycopg2 connection, no org_id, no prefix, no embeddings.
"""

import logging
from typing import Callable, Dict, List, Optional, Tuple, Any

import psycopg2
from psycopg2 import extras

from abra.types import Binding, Content, HotTag, CatcodeEntry, SearchResult
from abra.pii import PiiChecker, check_pii

logger = logging.getLogger(__name__)


class AbraStore:
    """
    Core store for abra bindings, content, catcodes, and hot tags.

    Constructor args:
        dsn: PostgreSQL connection string. Used if get_conn/put_conn not provided.
        get_conn: Callable that returns a DB connection. For pool integration.
        put_conn: Callable that accepts a connection to return it. For pool integration.
        embed_fn: Callable(str) -> list[float]. For vector search.
        org_id: Multi-tenancy filter. None = no filter (abra default).
        table_prefix: Prefix for table names. "" = abra, "abra_" = amebo local.
        pii_checker: PiiChecker instance. Override for custom PII rules.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        get_conn: Optional[Callable] = None,
        put_conn: Optional[Callable] = None,
        embed_fn: Optional[Callable] = None,
        org_id: Optional[int] = None,
        table_prefix: str = "",
        pii_checker: Optional[PiiChecker] = None,
    ):
        self._dsn = dsn
        self._get_conn = get_conn
        self._put_conn = put_conn
        self._own_conn = None  # Managed connection if using dsn
        self.embed_fn = embed_fn
        self.org_id = org_id
        self.table_prefix = table_prefix
        self.pii_checker = pii_checker or PiiChecker()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def get_conn(self):
        """Get a database connection. Uses injected factory or creates from dsn."""
        if self._get_conn:
            return self._get_conn()
        if self._own_conn is None or self._own_conn.closed:
            if not self._dsn:
                raise RuntimeError(
                    "AbraStore needs either dsn or get_conn/put_conn. "
                    "Pass dsn='postgresql://...' or inject a connection factory."
                )
            self._own_conn = psycopg2.connect(self._dsn)
        return self._own_conn

    def put_conn(self, conn):
        """Return a connection. Uses injected returner or keeps own connection open."""
        if self._put_conn:
            self._put_conn(conn)
        # If using own connection, just leave it open (reuse)

    def close(self):
        """Close own connection if we created one."""
        if self._own_conn and not self._own_conn.closed:
            self._own_conn.close()
            self._own_conn = None

    # ------------------------------------------------------------------
    # Table names (overridable via prefix)
    # ------------------------------------------------------------------

    @property
    def t_bindings(self) -> str:
        return f"{self.table_prefix}bindings"

    @property
    def t_content(self) -> str:
        return f"{self.table_prefix}content"

    @property
    def t_hot_tags(self) -> str:
        return f"{self.table_prefix}hot_tags"

    @property
    def t_catcode_registry(self) -> str:
        return f"{self.table_prefix}catcode_registry"

    # ------------------------------------------------------------------
    # Tenancy filtering
    # ------------------------------------------------------------------

    def _org_filter(self) -> Tuple[str, List]:
        """
        Returns (sql_fragment, params) for org_id filtering.
        Empty when org_id is None (abra default — no tenancy).
        """
        if self.org_id is None:
            return "", []
        return "org_id = %s AND ", [self.org_id]

    def _org_insert_cols(self) -> Tuple[str, str, List]:
        """
        Returns (col_names, placeholders, params) for org_id in INSERT.
        Empty when org_id is None.
        """
        if self.org_id is None:
            return "", "", []
        return "org_id, ", "%s, ", [self.org_id]

    # ------------------------------------------------------------------
    # Read: Bindings
    # ------------------------------------------------------------------

    def bindings_for(
        self,
        name: str,
        scope: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> List[Binding]:
        """Find all bindings for a name (case-insensitive)."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            conditions = [f"{org_clause}LOWER(name) = LOWER(%s)"]
            params = org_params + [name]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)
            if workspace_id and self.org_id is not None:
                conditions.append("(workspace_id = %s OR workspace_id IS NULL)")
                params.append(workspace_id)

            where = " AND ".join(conditions)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, scope, name, relationship, target_type,
                           target_ref, qualifier, permanence, source_date, catcode
                    FROM {self.t_bindings}
                    WHERE {where}
                    ORDER BY relationship, name
                """, params)
                return [self._row_to_binding(r) for r in cur.fetchall()]
        finally:
            self.put_conn(conn)

    def bindings_for_names(
        self,
        names: List[str],
        scope: Optional[str] = None,
    ) -> List[Binding]:
        """Batch lookup: find bindings for multiple names at once."""
        if not names:
            return []
        conn = self.get_conn()
        try:
            lower_names = [n.lower() for n in names]
            org_clause, org_params = self._org_filter()
            conditions = [f"{org_clause}LOWER(name) = ANY(%s)"]
            params = org_params + [lower_names]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)

            where = " AND ".join(conditions)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, scope, name, relationship, target_type,
                           target_ref, qualifier, permanence, source_date, catcode
                    FROM {self.t_bindings}
                    WHERE {where}
                    ORDER BY name, relationship
                """, params)
                return [self._row_to_binding(r) for r in cur.fetchall()]
        finally:
            self.put_conn(conn)

    def who(self, term: str, scope: Optional[str] = None) -> List[Binding]:
        """Find names by topic keyword (searches qualifier and target_ref)."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            params = org_params + [f"%{term}%", f"%{term}%"]
            scope_clause = ""
            if scope:
                scope_clause = "AND scope = %s"
                params.append(scope)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT DISTINCT name, qualifier, source_date, scope,
                           relationship, target_type, target_ref
                    FROM {self.t_bindings}
                    WHERE {org_clause}(qualifier ILIKE %s OR target_ref ILIKE %s)
                    {scope_clause}
                    ORDER BY name
                """, params)
                return [self._row_to_binding(r) for r in cur.fetchall()]
        finally:
            self.put_conn(conn)

    def find_names(self, scope: str, prefix: str) -> List[Binding]:
        """Find existing names matching a prefix."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT DISTINCT name, relationship, target_ref, scope,
                           target_type, qualifier
                    FROM {self.t_bindings}
                    WHERE {org_clause}scope = %s AND name LIKE %s
                    ORDER BY name
                """, org_params + [scope, f"{prefix}%"])
                return [self._row_to_binding(r) for r in cur.fetchall()]
        finally:
            self.put_conn(conn)

    # ------------------------------------------------------------------
    # Read: Content
    # ------------------------------------------------------------------

    def get_content(self, content_id: int) -> Optional[Content]:
        """Get a content blob by ID."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, source_file, content, note_date, catcode, created_at
                    FROM {self.t_content}
                    WHERE {org_clause}id = %s
                """, org_params + [content_id])
                row = cur.fetchone()
                return self._row_to_content(row) if row else None
        finally:
            self.put_conn(conn)

    def search_content(
        self,
        query: str,
        limit: int = 10,
        scope: Optional[str] = None,
    ) -> List[SearchResult]:
        """
        Search content by embedding similarity.

        Requires embed_fn to be set. Returns SearchResult with similarity scores.
        Override rank_results() to customize boosting/filtering.
        """
        if not self.embed_fn:
            logger.warning("search_content called without embed_fn — no results")
            return []

        conn = self.get_conn()
        try:
            query_embedding = self.embed_fn(query)
            org_clause, org_params = self._org_filter()

            params = [query_embedding] + org_params + [query_embedding, limit * 2]

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, source_file, content, note_date, catcode, created_at,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM {self.t_content}
                    WHERE {org_clause}embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                """, params)
                raw_results = cur.fetchall()

            # Convert to SearchResult and apply custom ranking
            results = [
                SearchResult(
                    content=self._row_to_content(r),
                    similarity=float(r.get('similarity', 0)),
                )
                for r in raw_results
            ]

            return self.rank_results(results, query)[:limit]

        except Exception as e:
            logger.warning(f"Content search failed: {e}")
            return []
        finally:
            self.put_conn(conn)

    def rank_results(
        self, results: List[SearchResult], query: str
    ) -> List[SearchResult]:
        """
        Rank/filter search results. Override this for custom boosting.

        Default: return as-is (already sorted by similarity from DB).
        Amebo overrides to boost project docs over contact stubs.
        """
        return results

    # ------------------------------------------------------------------
    # Read: Hot tags
    # ------------------------------------------------------------------

    def hot_tags(self, scope: Optional[str] = None) -> List[HotTag]:
        """Get active hot tags (not expired)."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            conditions = [f"{org_clause}(expires_at IS NULL OR expires_at > NOW())"]
            params = org_params[:]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)

            where = " AND ".join(conditions)

            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT scope, name, priority, added_at, expires_at
                    FROM {self.t_hot_tags}
                    WHERE {where}
                    ORDER BY priority DESC, added_at DESC
                """, params)
                return [self._row_to_hot_tag(r) for r in cur.fetchall()]
        finally:
            self.put_conn(conn)

    def is_hot(self, name: str, scope: Optional[str] = None) -> bool:
        """Check if a name is currently hot-tagged."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            conditions = [
                f"{org_clause}LOWER(name) = LOWER(%s)",
                "(expires_at IS NULL OR expires_at > NOW())",
            ]
            params = org_params + [name]

            if scope:
                conditions.append("scope = %s")
                params.append(scope)

            where = " AND ".join(conditions)

            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT 1 FROM {self.t_hot_tags} WHERE {where} LIMIT 1",
                    params,
                )
                return cur.fetchone() is not None
        finally:
            self.put_conn(conn)

    # ------------------------------------------------------------------
    # Write: Bindings
    # ------------------------------------------------------------------

    def write_binding(
        self,
        scope: str,
        name: str,
        relationship: str,
        target_type: str,
        target_ref: str,
        qualifier: Optional[str] = None,
        permanence: str = "CURRENT",
        source_date=None,
        catcode: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Optional[int]:
        """
        Write a single binding. Rejects PII in target_ref.
        Returns binding ID, or None if rejected.
        """
        if self.pii_checker.has_pii(target_ref):
            logger.warning(f"PII rejected: {name} {relationship} {target_ref[:40]}...")
            return None

        conn = self.get_conn()
        try:
            org_cols, org_phs, org_params = self._org_insert_cols()
            ws_cols = ", workspace_id" if workspace_id else ""
            ws_phs = ", %s" if workspace_id else ""
            ws_params = [workspace_id] if workspace_id else []

            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self.t_bindings}
                        ({org_cols}scope, name, relationship, target_type,
                         target_ref, qualifier, permanence, source_date, catcode
                         {ws_cols})
                    VALUES ({org_phs}%s, %s, %s, %s, %s, %s, %s, %s, %s {ws_phs})
                    RETURNING id
                """, org_params + [
                    scope, name, relationship, target_type,
                    target_ref, qualifier, permanence, source_date, catcode,
                ] + ws_params)
                binding_id = cur.fetchone()[0]
                conn.commit()
            return binding_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to write binding: {e}")
            raise
        finally:
            self.put_conn(conn)

    def rename_name(self, scope: str, old_name: str, new_name: str) -> int:
        """Rename a pet name across all its bindings. Returns count updated."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {self.t_bindings}
                    SET name = %s
                    WHERE {org_clause}scope = %s AND name = %s
                """, [new_name] + org_params + [scope, old_name])
                count = cur.rowcount
                conn.commit()
            return count
        finally:
            self.put_conn(conn)

    # ------------------------------------------------------------------
    # Write: Content
    # ------------------------------------------------------------------

    def store_content(
        self,
        source_file: Optional[str],
        content: str,
        note_date=None,
        catcode: Optional[str] = None,
        embedding=None,
        workspace_id: Optional[str] = None,
    ) -> int:
        """
        Store a content blob. Returns content ID.

        If embedding is None and embed_fn is set, generates embedding automatically.
        """
        if embedding is None and self.embed_fn:
            embedding = self.embed_fn(content)

        conn = self.get_conn()
        try:
            org_cols, org_phs, org_params = self._org_insert_cols()
            ws_cols = ", workspace_id" if workspace_id else ""
            ws_phs = ", %s" if workspace_id else ""
            ws_params = [workspace_id] if workspace_id else []

            emb_cast = "::vector" if embedding is not None else ""

            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self.t_content}
                        ({org_cols}source_file, content, embedding, note_date,
                         catcode {ws_cols})
                    VALUES ({org_phs}%s, %s, %s{emb_cast}, %s, %s {ws_phs})
                    RETURNING id
                """, org_params + [
                    source_file, content, embedding, note_date, catcode,
                ] + ws_params)
                content_id = cur.fetchone()[0]
                conn.commit()
            return content_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store content: {e}")
            raise
        finally:
            self.put_conn(conn)

    # ------------------------------------------------------------------
    # Write: Hot tags
    # ------------------------------------------------------------------

    def set_hot(
        self,
        scope: str,
        name: str,
        priority: int = 0,
        expires_at=None,
    ):
        """Set or update a hot tag."""
        conn = self.get_conn()
        try:
            org_cols, org_phs, org_params = self._org_insert_cols()
            # Build conflict target based on whether we have org_id
            if self.org_id is not None:
                conflict = "org_id, scope, name"
            else:
                conflict = "scope, name"

            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self.t_hot_tags}
                        ({org_cols}scope, name, priority, expires_at)
                    VALUES ({org_phs}%s, %s, %s, %s)
                    ON CONFLICT ({conflict})
                    DO UPDATE SET priority = EXCLUDED.priority,
                                  expires_at = EXCLUDED.expires_at,
                                  added_at = NOW()
                """, org_params + [scope, name, priority, expires_at])
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to set hot tag: {e}")
            raise
        finally:
            self.put_conn(conn)

    def unset_hot(self, scope: str, name: str):
        """Remove a hot tag."""
        conn = self.get_conn()
        try:
            org_clause, org_params = self._org_filter()
            with conn.cursor() as cur:
                cur.execute(f"""
                    DELETE FROM {self.t_hot_tags}
                    WHERE {org_clause}scope = %s AND LOWER(name) = LOWER(%s)
                """, org_params + [scope, name])
                conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to unset hot tag: {e}")
            raise
        finally:
            self.put_conn(conn)

    # ------------------------------------------------------------------
    # Catcodes
    # ------------------------------------------------------------------

    def register_catcode(
        self, catcode: str, parent_catcode: Optional[str], label: str
    ) -> str:
        """Register a position in the catcode tree. Returns catcode."""
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self.t_catcode_registry}
                        (catcode, parent_catcode, label)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (catcode) DO UPDATE SET label = EXCLUDED.label
                    RETURNING catcode
                """, (catcode, parent_catcode, label))
                result = cur.fetchone()[0]
                conn.commit()
            return result
        finally:
            self.put_conn(conn)

    def find_catcodes(self, prefix: str) -> List[CatcodeEntry]:
        """Find catcode entries by prefix."""
        conn = self.get_conn()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT catcode, parent_catcode, label
                    FROM {self.t_catcode_registry}
                    WHERE catcode LIKE %s
                    ORDER BY catcode
                """, (f"{prefix}%",))
                return [
                    CatcodeEntry(
                        catcode=r['catcode'],
                        parent_catcode=r['parent_catcode'],
                        label=r['label'],
                    )
                    for r in cur.fetchall()
                ]
        finally:
            self.put_conn(conn)

    def next_catcode(self, parent_catcode: str) -> str:
        """Get next sequential catcode under a parent. 2-char alphanumeric levels."""
        conn = self.get_conn()
        try:
            parent_len = len(parent_catcode)
            child_len = parent_len + 2
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT catcode FROM {self.t_catcode_registry}
                    WHERE parent_catcode = %s
                    ORDER BY catcode DESC LIMIT 1
                """, (parent_catcode,))
                row = cur.fetchone()

            if not row:
                return parent_catcode + "01"

            last = row[0][parent_len:child_len]
            chars = "0123456789abcdefghijklmnopqrstuvwxyz"
            idx = chars.index(last[0]) * 36 + chars.index(last[1]) + 1
            if idx >= 1296:
                raise ValueError(f"Catcode space exhausted under {parent_catcode}")
            return parent_catcode + chars[idx // 36] + chars[idx % 36]
        finally:
            self.put_conn(conn)

    def delete_catcode(self, catcode: str):
        """Delete a catcode and cascade: removes subtree and referencing bindings/content."""
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.t_bindings} WHERE catcode LIKE %s",
                    (f"{catcode}%",),
                )
                cur.execute(
                    f"DELETE FROM {self.t_content} WHERE catcode LIKE %s",
                    (f"{catcode}%",),
                )
                cur.execute(
                    f"DELETE FROM {self.t_catcode_registry} WHERE catcode = %s",
                    (catcode,),
                )
                conn.commit()
        finally:
            self.put_conn(conn)

    # ------------------------------------------------------------------
    # Row conversion helpers
    # ------------------------------------------------------------------

    def _row_to_binding(self, row: Dict) -> Binding:
        return Binding(
            id=row.get('id'),
            scope=row.get('scope', ''),
            name=row.get('name', ''),
            relationship=row.get('relationship', ''),
            target_type=row.get('target_type', ''),
            target_ref=row.get('target_ref', ''),
            qualifier=row.get('qualifier'),
            permanence=row.get('permanence', 'CURRENT'),
            source_date=row.get('source_date'),
            catcode=row.get('catcode'),
        )

    def _row_to_content(self, row: Dict) -> Content:
        return Content(
            id=row.get('id'),
            source_file=row.get('source_file'),
            content=row.get('content', ''),
            note_date=row.get('note_date'),
            catcode=row.get('catcode'),
            created_at=row.get('created_at'),
        )

    def _row_to_hot_tag(self, row: Dict) -> HotTag:
        return HotTag(
            scope=row.get('scope', ''),
            name=row.get('name', ''),
            priority=row.get('priority', 0),
            added_at=row.get('added_at'),
            expires_at=row.get('expires_at'),
        )

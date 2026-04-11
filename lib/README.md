# abra-lib

A brain extension library for naming things.

Pet names, catcodes, structured knowledge bindings — the portable core of
[abra](https://github.com/Cooperation-org/abra).

## Install

```bash
pip install abra-lib

# With embedding support:
pip install abra-lib[embeddings]
```

## Quick Start

```python
from abra import AbraStore

# Connect to an abra database
store = AbraStore(dsn="postgresql://user:pass@host/abra")

# Look up a name
bindings = store.bindings_for("leanne-ussher")
for b in bindings:
    print(f"  {b.name} {b.relationship} {b.target_ref}")

# Search content (requires embed_fn)
store = AbraStore(dsn="...", embed_fn=my_embed_function)
results = store.search_content("cooperative governance")
for r in results:
    print(f"  [{r.similarity:.0%}] {r.content.source_file}")

# Write
store.write_binding("golda", "peter", "IS", "text", "Peter Smith")
cid = store.store_content("notes/meeting.md", "Meeting notes...")

# Hot tags
store.set_hot("golda", "linkedtrust", priority=10)
hot = store.hot_tags()
```

## Override & Extend

The library is designed for projects that need abra's patterns with their
own infrastructure.

### Connection pool integration

```python
store = AbraStore(
    get_conn=my_pool.get_connection,
    put_conn=my_pool.return_connection,
)
```

### Multi-tenancy

```python
# Adds org_id filtering to all queries
store = AbraStore(dsn="...", org_id=5, table_prefix="abra_")
```

### Custom search ranking

```python
class ProjectBoostedStore(AbraStore):
    def rank_results(self, results, query):
        # Boost project docs over contact stubs
        project = [r for r in results if self._is_project_doc(r)]
        other = [r for r in results if not self._is_project_doc(r)]
        return project + other

    def _is_project_doc(self, result):
        sf = result.content.source_file or ""
        return any(sf.startswith(p) for p in ("projects/", "plans/", "Ideas/"))
```

### Custom PII rules

```python
from abra import PiiChecker
import re

class StrictPiiChecker(PiiChecker):
    def extra_patterns(self):
        return [re.compile(r'SSN:\s*\d{3}-\d{2}-\d{4}')]

store = AbraStore(dsn="...", pii_checker=StrictPiiChecker())
```

## Core Concepts

- **Bindings**: `(scope, name, relationship, target)` — a pet name bound to something
- **Catcodes**: Positional codes in a hierarchical space (not labels)
- **Hot tags**: Priority flags that surface names in working memory
- **Content**: Scrubbed text blobs with optional embeddings for vector search
- **Scopes**: Namespaces for pet names (personal or group)

See the [abra spec](https://github.com/Cooperation-org/abra) for full details.

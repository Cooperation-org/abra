"""
Core data types for abra bindings.

These match the binding-format-v0.1 spec. They're plain dataclasses —
easy to construct from DB rows, easy to serialize, no ORM coupling.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List


@dataclass
class Binding:
    """
    A single binding: (name, relationship, target) in a scope.

    The fundamental unit of structured knowledge. A pet name bound to
    something through a typed relationship.

    Fields match the bindings table columns. id is optional (None before insert).
    """
    scope: str
    name: str
    relationship: str           # IS, HAS, ABOUT, RELATED, SAME_AS, ...
    target_type: str            # text, content, uri, name
    target_ref: str             # The value — text, content ID, URL, another name
    qualifier: Optional[str] = None
    permanence: str = "CURRENT"  # INTRINSIC, CURRENT, EPHEMERAL
    source_date: Optional[date] = None
    catcode: Optional[str] = None
    id: Optional[int] = None

    # Multi-tenancy fields (not in abra core, added by consumers)
    org_id: Optional[int] = None
    workspace_id: Optional[str] = None


@dataclass
class Content:
    """
    A content blob — scrubbed note text, project doc, reference material.
    Stored with optional embedding for vector search.
    """
    source_file: Optional[str] = None
    content: str = ""
    note_date: Optional[date] = None
    catcode: Optional[str] = None
    embedding: Optional[List[float]] = None
    id: Optional[int] = None
    created_at: Optional[datetime] = None

    # Multi-tenancy
    org_id: Optional[int] = None
    workspace_id: Optional[str] = None


@dataclass
class HotTag:
    """
    A priority flag on a name. Hot tags surface names in working memory —
    the assistant proactively considers these when building context.
    """
    scope: str
    name: str
    priority: int = 0
    added_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Multi-tenancy
    org_id: Optional[int] = None


@dataclass
class CatcodeEntry:
    """
    A position in the catcode registry tree.
    Catcodes are spatial coordinates, not labels.
    """
    catcode: str
    parent_catcode: Optional[str] = None
    label: str = ""


@dataclass
class SearchResult:
    """A content search result with similarity score."""
    content: Content
    similarity: float = 0.0

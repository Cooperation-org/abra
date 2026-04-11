"""
PII detection for abra bindings.

No PII in the binding store. This module provides the default patterns.
Projects can subclass PiiChecker to add domain-specific rules.
"""

import re
from typing import List, Optional


# Default PII patterns (email, phone, zip code)
DEFAULT_PII_PATTERNS = [
    re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'),           # email
    re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),      # US phone
    re.compile(r'\b\d{5}(-\d{4})?\b'),                  # US zip
]


class PiiChecker:
    """
    Checks text for PII. Subclass to add project-specific patterns.

    Usage:
        checker = PiiChecker()
        if checker.has_pii("email me at foo@bar.com"):
            # reject or scrub

        # Custom patterns:
        class StrictChecker(PiiChecker):
            def extra_patterns(self):
                return [re.compile(r'SSN:\s*\d{3}-\d{2}-\d{4}')]
    """

    def __init__(self, patterns: Optional[List[re.Pattern]] = None):
        self._patterns = patterns or DEFAULT_PII_PATTERNS

    def has_pii(self, text: str) -> bool:
        """Check if text contains PII."""
        for pattern in self.all_patterns():
            if pattern.search(text):
                return True
        return False

    def all_patterns(self) -> List[re.Pattern]:
        """All PII patterns including extras. Override-friendly."""
        return self._patterns + self.extra_patterns()

    def extra_patterns(self) -> List[re.Pattern]:
        """Override this to add project-specific PII patterns."""
        return []


# Module-level convenience (uses default patterns)
_default_checker = PiiChecker()


def check_pii(text: str) -> bool:
    """Check if text contains PII using default patterns."""
    return _default_checker.has_pii(text)

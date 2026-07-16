"""Domain value objects for the CT200 QA Traceability System.

Value objects are immutable, equality-by-value types that encapsulate
domain concepts without identity.
"""

import hashlib


class ContentHash:
    """Deterministic hash of node content (heading + body).

    Uses SHA-256 to produce a consistent hash. Identical content
    always produces the same hash (CP-3.2).
    """

    @staticmethod
    def compute(heading: str, body: str) -> str:
        """Compute SHA-256 hash of heading + body concatenation.

        Args:
            heading: Node heading text.
            body: Node body text.

        Returns:
            Hex-encoded SHA-256 hash string.
        """
        content = f"{heading}\n{body}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ConfidenceScore:
    """Numeric confidence value (0.0-1.0) for lineage matching.

    Encapsulates the threshold logic: below threshold → needs_review.
    """

    def __init__(self, value: float, threshold: float = 0.75) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Confidence must be 0.0-1.0, got {value}")
        self.value = value
        self.threshold = threshold

    @property
    def needs_review(self) -> bool:
        """Whether this score falls below the confidence threshold."""
        return self.value < self.threshold

    @property
    def is_exact(self) -> bool:
        """Whether this is a perfect match (1.0)."""
        return self.value == 1.0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConfidenceScore):
            return self.value == other.value
        return NotImplemented

    def __repr__(self) -> str:
        return f"ConfidenceScore({self.value})"

"""ITreeEngine protocol — defines the contract for tree construction engines."""

from typing import Protocol

from ct200.domain.entities import DocumentTree, ParsedContent


class ITreeEngine(Protocol):
    """Protocol for building validated document trees from parsed content.

    Implementations must:
    - Build a hierarchical tree from ParsedContent
    - Assign heading, body, depth, parent, children, parsed_number,
      order_index, lineage_id, and content_hash to each node
    - Handle duplicate headings, skipped levels, and document ordering
    - Classify list items as body content
    - Reconstruct multi-page tables as single nodes
    - Validate the resulting tree structure
    - Compute content hashes for all nodes
    """

    def build_tree(self, content: ParsedContent, version_id: str = "") -> DocumentTree:
        """Construct a validated document tree from parsed content.

        Args:
            content: ParsedContent produced by the PDF parser.
            version_id: Version ID to assign to all nodes.

        Returns:
            Validated DocumentTree.

        Raises:
            TreeValidationError: If the resulting tree fails structural validation.
        """
        ...

    def validate(self, tree: DocumentTree) -> list[str]:
        """Validate tree structural integrity.

        Returns:
            List of validation error messages. Empty list means valid tree.
        """
        ...

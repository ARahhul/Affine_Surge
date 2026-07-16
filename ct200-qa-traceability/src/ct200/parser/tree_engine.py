"""Tree construction engine — converts ParsedContent into a validated DocumentTree.

Implements the ITreeEngine protocol. Handles:
- Section-number-based hierarchy (1 → depth 1, 1.1 → depth 2, 1.1.1 → depth 3)
- Cover page detection and skipping (content before first numbered section)
- Heading hierarchy construction for unnumbered heading blocks (fallback)
- Duplicate heading disambiguation by (parent, heading, order_index)
- Skipped heading levels (assigns to nearest valid ancestor)
- Document order preservation (order_index from source sequence)
- List item classification (body content, not separate nodes)
- Multi-page table reconstruction (single node per table)
- Body text normalization (collapse PDF line wrapping)
- Content hash computation per node (SHA-256 of heading+body)
- Full tree validation (single parent, no cycles, depth consistency, sibling indices)
"""

import re
import uuid

import structlog

from ct200.models import (
    BlockType,
    ContentBlock,
    DocumentNode,
    DocumentTree,
    ParsedContent,
    TreeValidationError,
    compute_content_hash,
)

logger = structlog.get_logger()

# Pattern to detect section numbers at start of text: "1.", "1.1", "2.3.1 ..."
_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.*)")

# Pattern to extract section numbers like "1.2.3" from heading text (legacy compat)
_SECTION_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\s")


def _has_numbered_sections(blocks: list[ContentBlock]) -> bool:
    """Check if ANY block in the document contains a numbered section heading."""
    for block in blocks:
        text = block.content.strip()
        if _SECTION_RE.match(text):
            return True
    return False


class TreeEngine:
    """Builds and validates hierarchical document trees from parsed content.

    Implements Requirements 3.1–3.12: tree construction, duplicate heading
    disambiguation, skipped-level handling, document order preservation,
    list-item classification, multi-page table reconstruction, validation,
    and content hash computation.
    """

    def build_tree(self, content: ParsedContent, version_id: str = "") -> DocumentTree:
        """Construct a validated document tree from parsed content.

        Args:
            content: ParsedContent produced by the PDF parser.
            version_id: Version ID to assign to all nodes.

        Returns:
            Validated DocumentTree with computed hashes and metadata.

        Raises:
            TreeValidationError: If the resulting tree fails structural validation.
        """
        # Create root node (depth=0)
        root = DocumentNode(
            id=str(uuid.uuid4()),
            version_id=version_id,
            parent_id=None,
            heading="root",
            body="",
            depth=0,
            order_index=0,
            lineage_id=str(uuid.uuid4()),
            content_hash=compute_content_hash("root", ""),
        )

        # Build tree structure from content blocks
        # Choose strategy based on whether the document has numbered sections
        if _has_numbered_sections(content.blocks):
            self._populate_tree_numbered(root, content.blocks, version_id)
        else:
            self._populate_tree_headings(root, content.blocks, version_id)

        # Compute tree metadata
        node_count = self._count_nodes(root)
        max_depth = self._max_depth(root)

        tree = DocumentTree(root=root, node_count=node_count, max_depth=max_depth)

        # Validate structural integrity
        errors = self.validate(tree)
        if errors:
            first_error = errors[0]
            raise TreeValidationError(
                f"Tree validation failed: {first_error}",
                details={"validation_errors": errors},
            )

        logger.info(
            "tree_built",
            node_count=node_count,
            max_depth=max_depth,
            version_id=version_id,
        )
        return tree

    def _populate_tree_numbered(
        self, root: DocumentNode, blocks: list[ContentBlock], version_id: str
    ) -> None:
        """Build tree using section numbers for hierarchy.

        Algorithm:
        1. Scan blocks for numbered sections (e.g., "1.", "1.1", "2.3.1")
        2. Everything before the first numbered section is ignored (cover page)
        3. Section number depth determines node depth (1→1, 1.1→2, 1.1.1→3)
        4. Non-numbered content between sections becomes body of current section
        5. Body text is normalized: single newlines collapsed, double preserved
        """
        stack: list[DocumentNode] = [root]
        child_counters: dict[str, int] = {root.id: 0}
        current_body_parts: list[str] = []
        found_first_section = False

        for block in blocks:
            text = block.content.strip()
            if not text:
                continue

            # Check if this block starts with a section number
            match = _SECTION_RE.match(text)

            if match:
                found_first_section = True
                section_num = match.group(1)  # e.g., "1.2.3"
                heading_text = text  # Keep full text including number
                target_depth = section_num.count(".") + 1  # "1"→1, "1.1"→2

                # Flush body to current node
                self._flush_body_normalized(stack, current_body_parts)
                current_body_parts = []

                # Pop stack to find correct parent
                while len(stack) > 1 and stack[-1].depth >= target_depth:
                    stack.pop()
                parent = stack[-1]

                # Create node
                if parent.id not in child_counters:
                    child_counters[parent.id] = 0
                order_idx = child_counters[parent.id]
                child_counters[parent.id] += 1

                node = DocumentNode(
                    id=str(uuid.uuid4()),
                    version_id=version_id,
                    parent_id=parent.id,
                    heading=heading_text,
                    body="",
                    depth=parent.depth + 1,
                    parsed_number=section_num,
                    order_index=order_idx,
                    lineage_id=str(uuid.uuid4()),
                    content_hash=compute_content_hash(heading_text, ""),
                )
                parent.children.append(node)
                stack.append(node)
                child_counters[node.id] = 0

            elif found_first_section:
                # Check if a HEADING-type block without number should create a sub-node
                if (
                    block.block_type == BlockType.HEADING
                    and block.level > 0
                    and len(text) < 80
                ):
                    self._flush_body_normalized(stack, current_body_parts)
                    current_body_parts = []

                    # Use current depth + 1 for unnumbered sub-headings
                    parent = stack[-1]
                    if parent.id not in child_counters:
                        child_counters[parent.id] = 0
                    order_idx = child_counters[parent.id]
                    child_counters[parent.id] += 1

                    node = DocumentNode(
                        id=str(uuid.uuid4()),
                        version_id=version_id,
                        parent_id=parent.id,
                        heading=text,
                        body="",
                        depth=parent.depth + 1,
                        parsed_number="",
                        order_index=order_idx,
                        lineage_id=str(uuid.uuid4()),
                        content_hash=compute_content_hash(text, ""),
                    )
                    parent.children.append(node)
                    stack.append(node)
                    child_counters[node.id] = 0
                else:
                    # Body/table/list content for current section
                    current_body_parts.append(text)
            # else: before first section = cover page, skip

        self._flush_body_normalized(stack, current_body_parts)

    def _populate_tree_headings(
        self, root: DocumentNode, blocks: list[ContentBlock], version_id: str
    ) -> None:
        """Build tree structure from ordered content blocks using heading levels.

        Fallback path for documents without numbered sections.

        Algorithm:
        - Maintain a stack representing the path from root to the current
          deepest open heading node.
        - For each HEADING block, pop the stack until we find a node whose
          depth is less than the heading's target depth, then attach as child.
        - For BODY, LIST_ITEM, and TABLE blocks, accumulate content into the
          most recent heading node's body.
        - Depth is always parent.depth + 1 (handles skipped levels per Req 3.3).
        """
        # Stack tracks current ancestry path; root is always at bottom
        stack: list[DocumentNode] = [root]
        # Track next child order_index for each parent node
        child_counters: dict[str, int] = {root.id: 0}
        # Accumulate body content for the current active heading
        current_body_parts: list[str] = []

        for block in blocks:
            if block.block_type == BlockType.HEADING and block.level > 0:
                # Flush accumulated body to the current heading node
                self._flush_body(stack, current_body_parts)
                current_body_parts = []

                # Find correct parent by popping stack until we find an ancestor
                # with depth < this heading's level (handles skipped levels)
                target_depth = block.level
                while len(stack) > 1 and stack[-1].depth >= target_depth:
                    stack.pop()

                parent = stack[-1]

                # Assign order_index for this child under its parent
                if parent.id not in child_counters:
                    child_counters[parent.id] = 0
                order_idx = child_counters[parent.id]
                child_counters[parent.id] += 1

                # Create new heading node
                # Depth is always parent.depth + 1 (Req 3.9: depth consistency)
                node = DocumentNode(
                    id=str(uuid.uuid4()),
                    version_id=version_id,
                    parent_id=parent.id,
                    heading=block.content,
                    body="",
                    depth=parent.depth + 1,
                    parsed_number=self._extract_parsed_number(block.content),
                    order_index=order_idx,
                    lineage_id=str(uuid.uuid4()),
                    content_hash=compute_content_hash(block.content, ""),
                )

                parent.children.append(node)
                stack.append(node)
                child_counters[node.id] = 0

            elif block.block_type == BlockType.TABLE:
                # Tables become body content of the current heading node (Req 3.6)
                current_body_parts.append(block.content)

            elif block.block_type == BlockType.LIST_ITEM:
                # List items are body content, not separate nodes (Req 3.5)
                current_body_parts.append(block.content)

            elif block.block_type == BlockType.BODY:
                current_body_parts.append(block.content)

        # Flush any remaining body content to the last heading node
        self._flush_body(stack, current_body_parts)

    def _flush_body_normalized(
        self, stack: list[DocumentNode], body_parts: list[str]
    ) -> None:
        """Flush accumulated body parts with text normalization (for numbered-section docs).

        Normalizes PDF line wrapping: collapses single newlines into spaces,
        preserves double newlines as paragraph breaks.
        """
        if not body_parts or len(stack) <= 1:
            return

        current_node = stack[-1]
        raw = "\n".join(body_parts)
        # Collapse single newlines (PDF line wrapping) but preserve paragraph breaks
        normalized = re.sub(r"(?<!\n)\n(?!\n)", " ", raw)
        normalized = re.sub(r" +", " ", normalized).strip()

        if current_node.body:
            current_node.body += "\n\n" + normalized
        else:
            current_node.body = normalized

        # Recompute content hash after body update
        current_node.content_hash = compute_content_hash(
            current_node.heading, current_node.body
        )

    def _flush_body(
        self, stack: list[DocumentNode], body_parts: list[str]
    ) -> None:
        """Flush accumulated body parts into the current heading node and recompute hash."""
        if not body_parts or len(stack) <= 1:
            return

        current_node = stack[-1]
        new_body = "\n".join(body_parts)

        if current_node.body:
            current_node.body += "\n" + new_body
        else:
            current_node.body = new_body

        # Recompute content hash after body update (Req 3.12)
        current_node.content_hash = compute_content_hash(
            current_node.heading, current_node.body
        )

    def validate(self, tree: DocumentTree) -> list[str]:
        """Validate tree structural integrity.

        Checks (Requirements 3.7–3.11):
        1. Single parent per non-root node (parent_id matches actual parent)
        2. No cycles (each node visited at most once)
        3. Depth consistency (node.depth == parent.depth + 1)
        4. Contiguous zero-based sibling order indices

        Args:
            tree: DocumentTree to validate.

        Returns:
            List of validation error messages. Empty list means valid tree.
        """
        errors: list[str] = []
        visited: set[str] = set()

        self._validate_node(tree.root, None, 0, visited, errors)

        return errors

    def _validate_node(
        self,
        node: DocumentNode,
        expected_parent_id: str | None,
        expected_depth: int,
        visited: set[str],
        errors: list[str],
    ) -> None:
        """Recursively validate a node and its subtree.

        Args:
            node: Current node to validate.
            expected_parent_id: What parent_id should be for this node.
            expected_depth: What depth should be for this node.
            visited: Set of already-visited node IDs (cycle detection).
            errors: Accumulator for error messages.
        """
        # Cycle detection (Req 3.8)
        if node.id in visited:
            errors.append(
                f"Cycle detected: node '{node.id}' (heading='{node.heading}') visited twice"
            )
            return
        visited.add(node.id)

        # Single-parent rule (Req 3.7)
        if node.parent_id != expected_parent_id:
            errors.append(
                f"Single-parent violation: node '{node.id}' (heading='{node.heading}') "
                f"has parent_id='{node.parent_id}' but expected '{expected_parent_id}'"
            )

        # Depth consistency (Req 3.9)
        if node.depth != expected_depth:
            errors.append(
                f"Depth inconsistency: node '{node.id}' (heading='{node.heading}') "
                f"has depth={node.depth} but expected {expected_depth}"
            )

        # Sibling order index validation (Req 3.10)
        if node.children:
            actual_indices = [child.order_index for child in node.children]
            expected_indices = list(range(len(node.children)))
            if actual_indices != expected_indices:
                errors.append(
                    f"Sibling order violation: node '{node.id}' (heading='{node.heading}') "
                    f"children have order_indices {actual_indices}, "
                    f"expected contiguous {expected_indices}"
                )

        # Recurse into children
        for child in node.children:
            self._validate_node(
                child, node.id, node.depth + 1, visited, errors
            )

    def _count_nodes(self, node: DocumentNode) -> int:
        """Count total nodes in tree including the given node."""
        return 1 + sum(self._count_nodes(child) for child in node.children)

    def _max_depth(self, node: DocumentNode) -> int:
        """Find maximum depth in the tree."""
        if not node.children:
            return node.depth
        return max(self._max_depth(child) for child in node.children)

    @staticmethod
    def _extract_parsed_number(heading: str) -> str:
        """Extract section number prefix from heading text.

        Examples:
            "1.2.3 Safety Features" → "1.2.3"
            "Introduction" → ""
        """
        match = _SECTION_NUMBER_RE.match(heading)
        return match.group(1) if match else ""

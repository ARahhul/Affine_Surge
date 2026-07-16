"""Unit tests for DiffVersionsUseCase.

Tests Requirements 5.5, 5.6, 5.7 and CP-5.3 (version immutability).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ct200.application.versioning import DiffVersionsUseCase
from ct200.domain.entities import NodeChange, VersionDiff


class _FakeNode:
    """Minimal node-like object for testing."""

    def __init__(self, id: str, lineage_id: str, content_hash: str):
        self.id = id
        self.lineage_id = lineage_id
        self.content_hash = content_hash


class _FakeVersion:
    """Minimal version-like object for testing."""

    def __init__(self, id: str):
        self.id = id


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.mark.asyncio
class TestDiffVersionsUseCase:
    """Tests for version diff computation."""

    async def test_added_nodes_detected(self, mock_session):
        """Nodes in version B but not in A are classified as added."""
        use_case = DiffVersionsUseCase(mock_session)

        # Mock repos
        with (
            patch.object(use_case._version_repo, "get_by_id") as mock_get_ver,
            patch.object(use_case._node_repo, "get_tree") as mock_get_tree,
        ):
            mock_get_ver.side_effect = [
                _FakeVersion("v1"),
                _FakeVersion("v2"),
            ]
            mock_get_tree.side_effect = [
                [_FakeNode("n1", "lin-1", "hash-a")],  # version A
                [
                    _FakeNode("n1", "lin-1", "hash-a"),
                    _FakeNode("n2", "lin-2", "hash-b"),  # new in B
                ],
            ]

            result = await use_case.execute("v1", "v2")

        assert result.added_nodes == ["lin-2"]
        assert result.removed_nodes == []
        assert result.modified_nodes == []

    async def test_removed_nodes_detected(self, mock_session):
        """Nodes in version A but not in B are classified as removed."""
        use_case = DiffVersionsUseCase(mock_session)

        with (
            patch.object(use_case._version_repo, "get_by_id") as mock_get_ver,
            patch.object(use_case._node_repo, "get_tree") as mock_get_tree,
        ):
            mock_get_ver.side_effect = [
                _FakeVersion("v1"),
                _FakeVersion("v2"),
            ]
            mock_get_tree.side_effect = [
                [
                    _FakeNode("n1", "lin-1", "hash-a"),
                    _FakeNode("n2", "lin-2", "hash-b"),
                ],
                [_FakeNode("n1", "lin-1", "hash-a")],  # lin-2 removed
            ]

            result = await use_case.execute("v1", "v2")

        assert result.added_nodes == []
        assert result.removed_nodes == ["lin-2"]
        assert result.modified_nodes == []

    async def test_modified_nodes_detected(self, mock_session):
        """Nodes with same lineage but different hash are classified as modified."""
        use_case = DiffVersionsUseCase(mock_session)

        with (
            patch.object(use_case._version_repo, "get_by_id") as mock_get_ver,
            patch.object(use_case._node_repo, "get_tree") as mock_get_tree,
        ):
            mock_get_ver.side_effect = [
                _FakeVersion("v1"),
                _FakeVersion("v2"),
            ]
            mock_get_tree.side_effect = [
                [_FakeNode("n1", "lin-1", "hash-old")],
                [_FakeNode("n2", "lin-1", "hash-new")],  # same lineage, different hash
            ]

            result = await use_case.execute("v1", "v2")

        assert result.added_nodes == []
        assert result.removed_nodes == []
        assert len(result.modified_nodes) == 1
        change = result.modified_nodes[0]
        assert change.lineage_id == "lin-1"
        assert change.change_type == "direct"
        assert change.old_hash == "hash-old"
        assert change.new_hash == "hash-new"

    async def test_combined_diff(self, mock_session):
        """Full scenario with added, removed, and modified nodes."""
        use_case = DiffVersionsUseCase(mock_session)

        with (
            patch.object(use_case._version_repo, "get_by_id") as mock_get_ver,
            patch.object(use_case._node_repo, "get_tree") as mock_get_tree,
        ):
            mock_get_ver.side_effect = [
                _FakeVersion("v1"),
                _FakeVersion("v2"),
            ]
            mock_get_tree.side_effect = [
                [
                    _FakeNode("a1", "lin-1", "h1"),
                    _FakeNode("a2", "lin-2", "h2"),
                    _FakeNode("a3", "lin-3", "h3"),
                ],
                [
                    _FakeNode("b1", "lin-1", "h1"),        # unchanged
                    _FakeNode("b2", "lin-2", "h2-mod"),    # modified
                    _FakeNode("b4", "lin-4", "h4"),        # added
                ],
            ]

            result = await use_case.execute("v1", "v2")

        assert "lin-4" in result.added_nodes
        assert "lin-3" in result.removed_nodes
        assert len(result.modified_nodes) == 1
        assert result.modified_nodes[0].lineage_id == "lin-2"

    async def test_version_not_found_raises(self, mock_session):
        """Missing version ID raises ValueError."""
        use_case = DiffVersionsUseCase(mock_session)

        with patch.object(use_case._version_repo, "get_by_id") as mock_get_ver:
            mock_get_ver.return_value = None

            with pytest.raises(ValueError, match="Version not found"):
                await use_case.execute("nonexistent", "v2")

    async def test_empty_versions(self, mock_session):
        """Two empty versions produce no diffs."""
        use_case = DiffVersionsUseCase(mock_session)

        with (
            patch.object(use_case._version_repo, "get_by_id") as mock_get_ver,
            patch.object(use_case._node_repo, "get_tree") as mock_get_tree,
        ):
            mock_get_ver.side_effect = [
                _FakeVersion("v1"),
                _FakeVersion("v2"),
            ]
            mock_get_tree.side_effect = [[], []]

            result = await use_case.execute("v1", "v2")

        assert result.added_nodes == []
        assert result.removed_nodes == []
        assert result.modified_nodes == []

    async def test_diff_is_read_only(self, mock_session):
        """CP-5.3: Diff computation never calls write methods on repos."""
        use_case = DiffVersionsUseCase(mock_session)

        with (
            patch.object(use_case._version_repo, "get_by_id") as mock_get_ver,
            patch.object(use_case._node_repo, "get_tree") as mock_get_tree,
        ):
            mock_get_ver.side_effect = [
                _FakeVersion("v1"),
                _FakeVersion("v2"),
            ]
            mock_get_tree.side_effect = [
                [_FakeNode("n1", "l1", "h1")],
                [_FakeNode("n2", "l1", "h2")],
            ]

            await use_case.execute("v1", "v2")

        # Verify no write operations were performed on the session
        mock_session.add.assert_not_called()
        mock_session.add_all.assert_not_called()
        mock_session.delete.assert_not_called()
        mock_session.execute.assert_not_called()  # We patched the repos

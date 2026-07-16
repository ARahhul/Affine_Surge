"""Parser hardening tests — fail-closed behavior for pathological inputs.

Validates Requirements 2.9 (structured error responses) and 2.10
(pathological input detection) by verifying the parser rejects invalid,
corrupt, oversized, and pathologically nested PDFs with the correct
exception types and never produces partial output.
"""

import asyncio
import os

import pytest

# Ensure required env vars are set before importing config-dependent modules
os.environ.setdefault("NVIDIA_NIM_API_KEY", "test-key-for-hardening")
os.environ.setdefault("AUTH_SECRET_KEY", "test-secret-for-hardening")

from ct200.domain.exceptions import (
    FileTooLargeError,
    InvalidFileFormatError,
    ParsingError,
    PathologicalInputError,
)
from ct200.infrastructure.parser.pymupdf_parser import PyMuPDFParser
from tests.fixtures.pdf_fixtures import (
    CORRUPT_PDF,
    EMPTY_BYTES,
    MINIMAL_VALID_PDF,
    NOT_A_PDF,
    TRUNCATED_AFTER_MAGIC,
)


@pytest.fixture
def parser() -> PyMuPDFParser:
    """Create a parser instance for testing."""
    return PyMuPDFParser()


class TestMagicByteValidation:
    """Reject files that don't start with %PDF- magic bytes."""

    @pytest.mark.asyncio
    async def test_rejects_plain_text(self, parser: PyMuPDFParser) -> None:
        """Plain text content raises InvalidFileFormatError."""
        with pytest.raises(InvalidFileFormatError) as exc_info:
            await parser.parse(NOT_A_PDF, "not_a_pdf.txt")
        assert "magic-byte" in exc_info.value.message.lower()
        assert exc_info.value.details["filename"] == "not_a_pdf.txt"

    @pytest.mark.asyncio
    async def test_rejects_empty_input(self, parser: PyMuPDFParser) -> None:
        """Empty bytes raise InvalidFileFormatError."""
        with pytest.raises(InvalidFileFormatError):
            await parser.parse(EMPTY_BYTES, "empty.pdf")

    @pytest.mark.asyncio
    async def test_rejects_random_bytes(self, parser: PyMuPDFParser) -> None:
        """Random binary content raises InvalidFileFormatError."""
        random_bytes = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08"
        with pytest.raises(InvalidFileFormatError):
            await parser.parse(random_bytes, "random.pdf")


class TestFileSizeValidation:
    """Reject files exceeding the configured max upload size."""

    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self, parser: PyMuPDFParser) -> None:
        """File exceeding 50MB raises FileTooLargeError."""
        # Create a byte string just over the limit (50MB + 1 byte)
        oversized = b"%PDF-" + b"x" * (50 * 1024 * 1024 + 1)
        with pytest.raises(FileTooLargeError) as exc_info:
            await parser.parse(oversized, "huge.pdf")
        assert "50MB" in exc_info.value.message or "limit" in exc_info.value.message.lower()
        assert exc_info.value.details["filename"] == "huge.pdf"

    @pytest.mark.asyncio
    async def test_accepts_file_at_boundary(self, parser: PyMuPDFParser) -> None:
        """File exactly at 50MB limit passes size check (may fail on content).

        This test verifies the size check itself doesn't reject at the boundary.
        The file will likely fail on parse since it's not valid PDF content,
        but it should NOT raise FileTooLargeError.
        """
        at_boundary = b"%PDF-" + b"x" * (50 * 1024 * 1024 - 5)
        # Should pass size validation but may fail parsing — that's expected
        with pytest.raises((ParsingError, PathologicalInputError)):
            await parser.parse(at_boundary, "boundary.pdf")


class TestCorruptPdfHandling:
    """Ensure corrupt PDFs produce ParsingError, never partial output."""

    @pytest.mark.asyncio
    async def test_truncated_pdf_raises_parsing_error(self, parser: PyMuPDFParser) -> None:
        """PDF with valid header but truncated body raises ParsingError."""
        with pytest.raises(ParsingError) as exc_info:
            await parser.parse(CORRUPT_PDF, "corrupt.pdf")
        assert exc_info.value.details["filename"] == "corrupt.pdf"

    @pytest.mark.asyncio
    async def test_truncated_after_magic_raises_parsing_error(self, parser: PyMuPDFParser) -> None:
        """PDF with only magic bytes raises ParsingError."""
        with pytest.raises(ParsingError) as exc_info:
            await parser.parse(TRUNCATED_AFTER_MAGIC, "truncated.pdf")
        assert exc_info.value.details["filename"] == "truncated.pdf"


class TestPathologicalNestingDetection:
    """Reject documents with outline nesting exceeding 20 levels."""

    @pytest.mark.asyncio
    async def test_rejects_deep_nesting_via_mock(
        self, parser: PyMuPDFParser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Document with TOC nesting > 20 raises PathologicalInputError.

        Uses monkeypatching to simulate a document with deep nesting
        since creating an actual PDF with 21+ TOC levels is complex.
        """
        import fitz

        class FakeDoc:
            """Fake PyMuPDF document that reports deep nesting."""

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def __len__(self):
                return 1

            def get_toc(self, simple=True):
                # Return TOC entries with depth > MAX_NESTING_DEPTH (20)
                return [[21, "Deep Section", 1]]

            def close(self):
                pass

        def mock_open(*args, **kwargs):
            return FakeDoc()

        monkeypatch.setattr(fitz, "open", mock_open)

        with pytest.raises(PathologicalInputError) as exc_info:
            await parser.parse(MINIMAL_VALID_PDF, "deep_nested.pdf")

        assert "nesting depth" in exc_info.value.message.lower()
        assert exc_info.value.details["max_depth"] == 21
        assert exc_info.value.details["filename"] == "deep_nested.pdf"

    @pytest.mark.asyncio
    async def test_accepts_normal_nesting_via_mock(
        self, parser: PyMuPDFParser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Document with TOC nesting <= 20 is accepted."""
        import fitz

        class FakeDoc:
            """Fake PyMuPDF document with acceptable nesting."""

            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def __len__(self):
                return 1

            def __getitem__(self, idx):
                return FakePage()

            def get_toc(self, simple=True):
                return [[5, "Normal Section", 1], [10, "Sub Section", 2]]

            def close(self):
                pass

        class FakePage:
            """Fake page that returns empty content."""

            @property
            def rect(self):
                class Rect:
                    width = 612.0
                    height = 792.0
                return Rect()

            def get_text(self, mode="text", **kwargs):
                if mode == "dict":
                    return {"blocks": []}
                return ""

            def find_tables(self):
                return None

        def mock_open(*args, **kwargs):
            return FakeDoc()

        monkeypatch.setattr(fitz, "open", mock_open)

        # Should not raise PathologicalInputError
        result = await parser.parse(MINIMAL_VALID_PDF, "normal.pdf")
        assert result.filename == "normal.pdf"


class TestFailClosedBehavior:
    """Verify parser never produces partial output on error paths."""

    @pytest.mark.asyncio
    async def test_all_error_types_are_ct200_errors(self, parser: PyMuPDFParser) -> None:
        """Every error path raises a CT200Error subclass, never raw exceptions."""
        from ct200.domain.exceptions import CT200Error

        test_cases = [
            (NOT_A_PDF, "text.pdf"),  # InvalidFileFormatError
            (EMPTY_BYTES, "empty.pdf"),  # InvalidFileFormatError
            (CORRUPT_PDF, "corrupt.pdf"),  # ParsingError
        ]

        for pdf_bytes, filename in test_cases:
            with pytest.raises(CT200Error) as exc_info:
                await parser.parse(pdf_bytes, filename)
            # Verify structured error fields exist
            assert hasattr(exc_info.value, "message")
            assert hasattr(exc_info.value, "code")
            assert hasattr(exc_info.value, "status_code")
            assert hasattr(exc_info.value, "details")
            assert isinstance(exc_info.value.details, dict)

    @pytest.mark.asyncio
    async def test_error_response_includes_filename(self, parser: PyMuPDFParser) -> None:
        """All structured error responses include the filename in details."""
        test_cases = [
            (NOT_A_PDF, "my_file.pdf"),
            (CORRUPT_PDF, "broken_doc.pdf"),
        ]

        for pdf_bytes, filename in test_cases:
            with pytest.raises(Exception) as exc_info:
                await parser.parse(pdf_bytes, filename)
            assert exc_info.value.details.get("filename") == filename

    @pytest.mark.asyncio
    async def test_generic_exception_wrapped_as_parsing_error(
        self, parser: PyMuPDFParser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unexpected exceptions from PyMuPDF are wrapped as ParsingError."""
        import fitz

        def mock_open(*args, **kwargs):
            raise RuntimeError("Simulated PyMuPDF internal crash")

        monkeypatch.setattr(fitz, "open", mock_open)

        with pytest.raises(ParsingError) as exc_info:
            await parser.parse(MINIMAL_VALID_PDF, "crash.pdf")
        assert "Unexpected error" in exc_info.value.message
        assert exc_info.value.details["filename"] == "crash.pdf"

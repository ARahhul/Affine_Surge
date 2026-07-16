"""IParser protocol — contract for PDF parsing implementations."""

from typing import Protocol

from ct200.domain.entities import ParsedContent


class IParser(Protocol):
    """Protocol for PDF document parsers.

    Implementations must validate input (magic bytes, file size),
    apply timeout protection, and return structured ParsedContent.
    """

    async def parse(self, pdf_bytes: bytes, filename: str) -> ParsedContent:
        """Parse PDF bytes into structured content.

        Args:
            pdf_bytes: Raw bytes of the PDF file.
            filename: Original filename for error reporting and metadata.

        Returns:
            ParsedContent with extracted pages and blocks.

        Raises:
            InvalidFileFormatError: If magic-byte check fails.
            FileTooLargeError: If file exceeds configured size limit.
            TimeoutError: If parsing exceeds configured wall-clock timeout.
            PathologicalInputError: If content triggers pathological limits.
            ParsingError: For other parsing failures.
        """
        ...

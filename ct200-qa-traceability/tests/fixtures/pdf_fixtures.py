"""Test fixtures for malformed PDF input testing.

Provides byte-literal PDF fixtures for hardening tests without requiring
actual PDF files on disk.
"""

# Minimal valid PDF (1 page, no content)
MINIMAL_VALID_PDF = (
    b"%PDF-1.0\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n183\n%%EOF"
)

# Corrupt PDF: valid magic bytes but truncated/garbage content
CORRUPT_PDF = b"%PDF-1.0\nThis is not valid PDF content after the header."

# Not a PDF at all — plain text file
NOT_A_PDF = b"This is just a plain text file, not a PDF."

# Empty bytes
EMPTY_BYTES = b""

# PDF magic bytes only — truncated immediately after header
TRUNCATED_AFTER_MAGIC = b"%PDF-1.7\n"

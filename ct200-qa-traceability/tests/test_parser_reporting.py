"""Test parser reporting module."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("NVIDIA_NIM_API_KEY", "test")
os.environ.setdefault("AUTH_SECRET_KEY", "test")

import pytest
from ct200.parser.pymupdf_parser import PyMuPDFParser
from ct200.parser.reporting import (
    generate_parser_report,
    generate_validation_report,
    generate_reconciliation_report,
)

PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "pdf", "ct200_manual.pdf")


@pytest.mark.skipif(not os.path.exists(PDF_PATH), reason="PDF not found")
def test_parser_report_structure():
    parser = PyMuPDFParser()
    with open(PDF_PATH, "rb") as f:
        content = asyncio.run(parser.parse(f.read(), "ct200_manual.pdf"))
    report = generate_parser_report(content)
    d = report.to_dict()
    assert d["total_pages"] == 6
    assert d["total_blocks_extracted"] > 0
    assert "headings_extracted" in d


@pytest.mark.skipif(not os.path.exists(PDF_PATH), reason="PDF not found")
def test_validation_report():
    report = generate_validation_report(stripped_count=3, multi_column_pages=1)
    d = report.to_dict()
    assert d["repeated_headers_stripped"] == 3
    assert d["multi_column_pages"] == 1


@pytest.mark.skipif(not os.path.exists(PDF_PATH), reason="PDF not found")
def test_reconciliation_report():
    parser = PyMuPDFParser()
    with open(PDF_PATH, "rb") as f:
        content = asyncio.run(parser.parse(f.read(), "ct200_manual.pdf"))
    recon = generate_reconciliation_report(
        total_extracted_before_strip=130,
        content_after_strip=content,
        stripped_count=9,
    )
    d = recon.to_dict()
    assert d["total_extracted"] == 130
    assert d["unmapped_blocks"] == 9
    assert d["reconciliation_valid"] is True

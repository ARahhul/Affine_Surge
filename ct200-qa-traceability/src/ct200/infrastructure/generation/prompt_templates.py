"""Prompt templates for LLM generation.

Structurally separates system instructions from document content (CP-7.4).
System message contains only instructions; user message contains only document content
delimited by clear markers. Document content CANNOT alter system instructions.

Requirements: 7.3, 12.6
"""

from __future__ import annotations

SYSTEM_INSTRUCTION = """\
You are a QA test case generator for technical documentation. Your task is to \
produce structured, traceable test cases in strict JSON format.

Rules:
1. Output ONLY valid JSON matching the schema below.
2. Do NOT include markdown, commentary, or any text outside the JSON object.
3. Each test case must trace back to a specific section of the source document.
4. Prioritize safety-critical and regulatory-compliance scenarios.
5. Use clear, actionable steps that a manual tester can follow.

Output JSON Schema:
{
  "test_cases": [
    {
      "test_id": "TC-<sequential number>",
      "title": "<concise test title>",
      "description": "<what is being verified>",
      "preconditions": ["<prerequisite conditions>"],
      "steps": ["<step 1>", "<step 2>", ...],
      "expected_results": ["<expected outcome for each step>"],
      "priority": "high" | "medium" | "low",
      "traceability": "<section heading or number from source>"
    }
  ]
}
"""


def build_prompt(
    node_contents: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Build the chat messages list for NIM generation.

    Args:
        node_contents: List of dicts with 'heading' and 'body' keys
            representing selected document nodes.

    Returns:
        List of message dicts with 'role' and 'content' keys.
        System message contains ONLY instructions (never document content).
        User message contains ONLY document content (never instructions).
    """
    # Format document content with clear structural markers
    document_sections: list[str] = []
    for node in node_contents:
        heading = node.get("heading", "Untitled Section")
        body = node.get("body", "")
        document_sections.append(f"## {heading}\n{body}")

    document_text = "\n\n".join(document_sections)

    # User message uses delimiters to clearly separate content from any
    # potential injection attempts. The system message is FIXED and never
    # includes user-supplied data.
    user_content = (
        "Generate QA test cases for the following document sections.\n\n"
        "<DOCUMENT_CONTENT>\n"
        f"{document_text}\n"
        "</DOCUMENT_CONTENT>"
    )

    return [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_content},
    ]

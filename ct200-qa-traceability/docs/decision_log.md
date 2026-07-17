# Decision Log

Honest answers to three questions about what this system gets wrong, where corners were cut, and what's unhandled.

---

## 1. What's most likely to silently give wrong results without erroring?

The lineage matcher's positional fallback tier. When two document versions have structurally different section ordering (e.g., a new section inserted between existing ones), the positional strategy can silently assign a lineage_id linking a node in the new version to a completely unrelated node in the old version — confidence will be low (0.5–0.65) but above the default 0.75 threshold if the headings share words. The system won't error; it'll report "matched" with moderate confidence on a wrong pair. You'd catch it by auditing matches where `match_strategy = "positional"` and confidence < 0.8, or by surfacing `needs_review` status to a human reviewer rather than auto-accepting.

## 2. Where did you pick simplicity over correctness?

Document identity is tied to the uploaded filename, not to a stable document key or content fingerprint. Two users uploading the same PDF under different filenames create two separate document records with no connection between them. In production, a concurrent re-upload race could also create duplicate versions if two requests compute the same content_hash between the idempotency check and the commit — SQLite's WAL mode and the unique index on `(document_id, content_hash)` would catch this with a constraint error rather than silent duplication, but the error surfaces as a 500 instead of a clean retry response. This would break first under concurrent multi-user load.

## 3. One unhandled input and what happens?

A password-protected PDF. PyMuPDF's `fitz.open()` on an encrypted document raises a `RuntimeError` or returns zero pages depending on the protection type. The parser's generic `except Exception` wrapper catches this and raises `ParsingError("Unexpected error parsing PDF: ...")` — which returns HTTP 422 to the client — but the error message is opaque and doesn't tell the user "your PDF is encrypted, please provide the password or an unprotected copy." There's no mechanism to supply a decryption password to the ingestion endpoint.

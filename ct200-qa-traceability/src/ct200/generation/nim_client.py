"""NVIDIA NIM API client with retry logic.

HTTP client for NIM API (OpenAI-compatible chat completions endpoint).
- JSON mode request, response parsing, token count extraction
- Retry on schema validation failure (1 retry)
- Exponential backoff on transient HTTP errors (max 3 retries)
- Hard timeout of 60 seconds
- Configurable rate limit (default 40 requests/minute)

Requirements: 7.3, 7.6, 7.8, 7.9
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Transient HTTP status codes that warrant a retry
_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class QATestCase(BaseModel):
    """A single generated QA test case."""

    test_id: str
    title: str
    description: str
    preconditions: list[str]
    steps: list[str]
    expected_results: list[str]
    priority: str  # "high" | "medium" | "low"
    traceability: str  # section reference


class GenerationOutput(BaseModel):
    """Validated output schema for NIM generation responses."""

    test_cases: list[QATestCase]


@dataclass
class NIMResponse:
    """Parsed response from NIM API."""

    output: GenerationOutput
    input_tokens: int
    output_tokens: int
    raw_json: str


class NIMClientError(Exception):
    """Base exception for NIM client errors."""

    pass


class NIMTimeoutError(NIMClientError):
    """Raised when the NIM request exceeds the hard timeout."""

    pass


class NIMTransientError(NIMClientError):
    """Raised on transient HTTP errors after all retries exhausted."""

    pass


class NIMSchemaError(NIMClientError):
    """Raised when NIM response fails schema validation after retry."""

    pass


@dataclass
class NIMClient:
    """Async HTTP client for NVIDIA NIM API.

    Implements:
    - OpenAI-compatible chat completions endpoint
    - JSON mode for structured output
    - Schema validation with 1 retry on failure
    - Exponential backoff on transient errors (max 3)
    - Hard timeout enforcement
    - Per-minute rate limiting
    """

    base_url: str
    api_key: str
    model_id: str
    timeout_seconds: int = 60
    max_transient_retries: int = 3
    rate_limit_rpm: int = 40
    _request_timestamps: list[float] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def _enforce_rate_limit(self) -> None:
        """Enforce per-minute rate limit by sleeping if necessary."""
        async with self._lock:
            now = time.monotonic()
            # Remove timestamps older than 60 seconds
            self._request_timestamps = [ts for ts in self._request_timestamps if now - ts < 60.0]
            if len(self._request_timestamps) >= self.rate_limit_rpm:
                # Wait until the oldest request falls out of the window
                sleep_time = 60.0 - (now - self._request_timestamps[0])
                if sleep_time > 0:
                    logger.debug(f"Rate limit: sleeping {sleep_time:.2f}s")
                    await asyncio.sleep(sleep_time)
            self._request_timestamps.append(time.monotonic())

    async def _make_request(self, messages: list[dict[str, str]]) -> httpx.Response:
        """Make a single HTTP request to the NIM API with timeout."""
        await self._enforce_rate_limit()

        request_body = {
            "model": self.model_id,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds)) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
        return response

    async def _request_with_transient_retry(self, messages: list[dict[str, str]]) -> httpx.Response:
        """Execute request with exponential backoff on transient errors."""
        last_error: Exception | None = None

        for attempt in range(self.max_transient_retries + 1):
            try:
                response = await self._make_request(messages)

                if response.status_code == 200:
                    return response

                if response.status_code in _TRANSIENT_STATUS_CODES:
                    last_error = NIMTransientError(
                        f"HTTP {response.status_code}: {response.text[:200]}"
                    )
                    if attempt < self.max_transient_retries:
                        backoff = 2**attempt  # 1s, 2s, 4s
                        logger.warning(
                            f"Transient error (HTTP {response.status_code}), "
                            f"retry {attempt + 1}/{self.max_transient_retries} "
                            f"after {backoff}s"
                        )
                        await asyncio.sleep(backoff)
                        continue

                # Non-transient error — fail immediately
                raise NIMClientError(
                    f"NIM API error HTTP {response.status_code}: " f"{response.text[:500]}"
                )

            except httpx.TimeoutException as exc:
                raise NIMTimeoutError(
                    f"NIM request timed out after {self.timeout_seconds}s"
                ) from exc
            except httpx.HTTPError as exc:
                last_error = NIMTransientError(str(exc))
                if attempt < self.max_transient_retries:
                    backoff = 2**attempt
                    logger.warning(
                        f"HTTP error ({exc}), retry {attempt + 1}/"
                        f"{self.max_transient_retries} after {backoff}s"
                    )
                    await asyncio.sleep(backoff)
                    continue

        raise last_error or NIMTransientError("All retries exhausted")

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        """Extract content and token counts from NIM response."""
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return {
            "content": content,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        }

    def _validate_output(self, content: str) -> GenerationOutput:
        """Parse and validate the JSON output against the schema."""
        parsed = json.loads(content)
        return GenerationOutput.model_validate(parsed)

    async def generate(self, messages: list[dict[str, str]]) -> NIMResponse:
        """Generate test cases via NIM API.

        Handles full lifecycle:
        1. Make request with transient retry
        2. Parse response
        3. Validate schema — retry once on schema failure
        4. Return validated result

        Raises:
            NIMTimeoutError: Hard timeout exceeded.
            NIMTransientError: Transient errors after all retries.
            NIMSchemaError: Schema validation failed after 1 retry.
            NIMClientError: Non-transient API error.
        """
        response = await self._request_with_transient_retry(messages)
        parsed = self._parse_response(response)

        # Attempt schema validation
        try:
            output = self._validate_output(parsed["content"])
        except (json.JSONDecodeError, ValidationError) as first_error:
            logger.warning(f"Schema validation failed, retrying once: {first_error}")
            # Retry once on schema validation failure
            response = await self._request_with_transient_retry(messages)
            parsed = self._parse_response(response)
            try:
                output = self._validate_output(parsed["content"])
            except (json.JSONDecodeError, ValidationError) as second_error:
                raise NIMSchemaError(
                    f"Schema validation failed after retry: {second_error}"
                ) from second_error

        return NIMResponse(
            output=output,
            input_tokens=parsed["input_tokens"],
            output_tokens=parsed["output_tokens"],
            raw_json=parsed["content"],
        )

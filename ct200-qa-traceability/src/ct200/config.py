"""Application configuration loaded from environment variables via Pydantic Settings."""

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """CT200 QA Traceability System configuration.

    All settings are loaded from environment variables.
    Required variables will cause a validation error at startup if missing.
    """

    # Database
    database_url: str = Field(
        default="sqlite:///data/ct200.db",
        description="SQLite database URL",
    )

    # NVIDIA NIM
    nvidia_nim_api_key: str = Field(
        description="NVIDIA NIM API key (required)",
    )
    nvidia_nim_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="NVIDIA NIM base URL",
    )
    nvidia_nim_model_id: str = Field(
        default="z-ai/glm-5.2",
        description="NVIDIA NIM model identifier",
    )

    # Authentication
    auth_secret_key: str = Field(
        description="Secret key for token signing (required)",
    )

    # Rate Limits
    rate_limit_ingest: str = Field(
        default="10/minute",
        description="Rate limit for ingestion endpoint",
    )
    rate_limit_generate: str = Field(
        default="40/minute",
        description="Rate limit for generation endpoint",
    )

    # Timeouts
    parse_timeout_seconds: int = Field(
        default=120,
        description="Wall-clock timeout for PDF parsing in seconds",
        ge=1,
    )
    generation_timeout_seconds: int = Field(
        default=60,
        description="Hard timeout for LLM generation in seconds",
        ge=1,
    )

    # Versioning
    confidence_threshold: float = Field(
        default=0.75,
        description="Minimum confidence score for auto-accepting lineage matches",
        ge=0.0,
        le=1.0,
    )

    # Upload
    max_upload_size_mb: int = Field(
        default=50,
        description="Maximum upload file size in megabytes",
        ge=1,
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


def get_settings() -> Settings:
    """Create and validate settings from environment.

    Raises:
        SystemExit: If required environment variables are missing or fail validation.
            The error message clearly identifies which variables are missing.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing_fields: list[str] = []
        invalid_fields: list[str] = []

        for error in exc.errors():
            field_name = ".".join(str(loc) for loc in error["loc"])
            env_var = field_name.upper()
            if error["type"] == "missing":
                missing_fields.append(env_var)
            else:
                invalid_fields.append(f"{env_var}: {error['msg']}")

        parts: list[str] = ["Configuration validation failed at startup."]
        if missing_fields:
            parts.append(
                f"  Missing required environment variables: {', '.join(missing_fields)}"
            )
        if invalid_fields:
            parts.append(
                f"  Invalid environment variables: {'; '.join(invalid_fields)}"
            )

        error_message = "\n".join(parts)
        raise SystemExit(error_message) from exc

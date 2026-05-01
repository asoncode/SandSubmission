"""Runtime configuration for local development and deployment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Settings:
    """Environment-backed settings used by ingestion and later app services."""

    database_url: str
    tenant_id: str
    country_code: str
    data_dir: Path
    output_dir: Path
    openai_api_key: Optional[str]
    openai_model: str


def get_settings() -> Settings:
    """Return settings with conservative local defaults."""

    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://sand:sand@localhost:5432/sand_bulletin",
        ),
        tenant_id=os.getenv("SAND_TENANT_ID", "default"),
        country_code=os.getenv("SAND_COUNTRY_CODE", "RWA"),
        data_dir=Path(os.getenv("SAND_DATA_DIR", "docs/data")),
        output_dir=Path(os.getenv("SAND_OUTPUT_DIR", "outputs")),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
    )

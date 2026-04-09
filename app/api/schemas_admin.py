"""Schemas for admin endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ValidateKeyRequestSchema(BaseModel):
    provider: str
    key_id: str


class ReloadConfigRequestSchema(BaseModel):
    config_path: str | None = None

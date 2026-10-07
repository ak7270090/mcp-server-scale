"""Curated files: ``services.yaml`` (what to crawl), ``tool_overrides.yaml`` (what to expose)."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field

SERVICE_NAME_PATTERN = r"^[a-z][a-z0-9]*$"


class RestServiceSource(BaseModel):
    kind: Literal["rest"]
    name: str = Field(pattern=SERVICE_NAME_PATTERN)
    base_url: str
    openapi_url: str


class GrpcServiceSource(BaseModel):
    kind: Literal["grpc"]
    name: str = Field(pattern=SERVICE_NAME_PATTERN)
    target: str
    read_only_method_prefixes: list[str] = Field(default_factory=lambda: ["Get", "List", "Watch"])


ServiceSource = Annotated[RestServiceSource | GrpcServiceSource, Field(discriminator="kind")]


class ServicesFile(BaseModel):
    services: list[ServiceSource]


class ToolOverride(BaseModel):
    """Every discovered tool starts disabled; a reviewed entry here exposes it."""

    enabled: bool = False
    description: str | None = None


class ToolOverridesFile(BaseModel):
    tools: dict[str, ToolOverride] = Field(default_factory=dict)


def load_services_file(path: Path) -> list[ServiceSource]:
    return ServicesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).services


def load_tool_overrides(path: Path) -> dict[str, ToolOverride]:
    if not path.exists():
        return {}
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ToolOverridesFile.model_validate(content).tools

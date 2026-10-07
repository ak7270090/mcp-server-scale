"""Result filters: field projection (fewer tokens) and PII redaction."""

import re
from typing import Any

from apigateway.constants import REDACTED_TEXT, WRAPPED_RESULT_KEY


def select_fields(value: Any, fields: list[str]) -> Any:
    if not isinstance(value, dict):
        return value
    return {field_name: value[field_name] for field_name in fields if field_name in value}


def project_fields(
    structured: dict[str, Any], fields: list[str], is_wrapped: bool
) -> dict[str, Any]:
    """Keep only ``fields``; for a wrapped list result, apply to each item."""
    if not is_wrapped:
        return select_fields(structured, fields)
    inner = structured[WRAPPED_RESULT_KEY]
    if isinstance(inner, list):
        return {WRAPPED_RESULT_KEY: [select_fields(item, fields) for item in inner]}
    return {WRAPPED_RESULT_KEY: select_fields(inner, fields)}


class ResponseFilter:
    def __init__(self, redaction_patterns: dict[str, str]) -> None:
        self._redaction_patterns = [re.compile(pattern) for pattern in redaction_patterns.values()]

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for pattern in self._redaction_patterns:
                value = pattern.sub(REDACTED_TEXT, value)
            return value
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def apply(
        self, structured: dict[str, Any], fields: list[str] | None, is_wrapped: bool
    ) -> dict[str, Any]:
        projected = project_fields(structured, fields, is_wrapped) if fields else structured
        return self.redact(projected)

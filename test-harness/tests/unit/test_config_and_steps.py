from pathlib import Path

import pytest
from mcp import types

from mcpharness.config import load_harness_settings
from mcpharness.scenario_steps import (
    ToolCallFailedError,
    read_structured_result,
    run_replica_command,
)


def test_settings_read_env_file_named_by_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "phase.env"
    env_file.write_text(
        'HARNESS_TARGET_URL=http://localhost:9999/mcp\nHARNESS_EXPECTED_FAILURES=["affinity"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HARNESS_ENV_FILE", str(env_file))

    settings = load_harness_settings()

    assert settings.target_url == "http://localhost:9999/mcp"
    assert settings.expected_failures == {"affinity"}


def test_replica_command_rejects_unexpected_replica_id() -> None:
    with pytest.raises(ValueError, match="unexpected replica id"):
        run_replica_command("docker kill {replica}", "replica; rm -rf /", timeout_seconds=1)


def test_structured_result_unwraps_result_key() -> None:
    result = types.CallToolResult(content=[], structuredContent={"result": 5})

    assert read_structured_result(result) == 5


def test_structured_result_raises_on_tool_error() -> None:
    result = types.CallToolResult(
        content=[types.TextContent(type="text", text="boom")], isError=True
    )

    with pytest.raises(ToolCallFailedError, match="boom"):
        read_structured_result(result)

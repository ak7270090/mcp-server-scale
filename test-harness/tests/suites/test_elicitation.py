import pytest

from mcpharness.client_factory import create_mcp_connection
from mcpharness.config import HarnessSettings
from mcpharness.constants import CONFIRMATION_ANSWER_CONFIRMED, CONFIRMATION_QUESTION
from mcpharness.scenario_steps import ConfirmationResponder, ask_for_confirmation

pytestmark = [pytest.mark.anyio, pytest.mark.elicitation]


async def test_answer_reaches_the_waiting_tool(harness_settings: HarnessSettings) -> None:
    responder = ConfirmationResponder()
    async with create_mcp_connection(
        harness_settings, elicitation_callback=responder.answer
    ) as connection:
        answer = await ask_for_confirmation(connection.session)

    assert responder.received_questions == [CONFIRMATION_QUESTION]
    assert answer == CONFIRMATION_ANSWER_CONFIRMED

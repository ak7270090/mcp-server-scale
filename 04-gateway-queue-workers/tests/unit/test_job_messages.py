import pytest

from mcpqueue.job_messages import (
    JobInputRequired,
    JobProgress,
    JobRequest,
    JobResult,
    build_answers_subject,
    build_cancel_subject,
    build_results_subject,
    parse_worker_message,
)


@pytest.mark.parametrize(
    "message",
    [
        JobProgress(progress=2, total=3, message="2/3"),
        JobInputRequired(question="Proceed?", continuation_state={"step": 1}),
        JobResult(result={"replica_id": "w", "process_id": 1}),
    ],
)
def test_worker_messages_round_trip_through_json(message: object) -> None:
    assert parse_worker_message(message.model_dump_json().encode()) == message


def test_each_job_gets_a_unique_id() -> None:
    first = JobRequest(tool_name="get_replica_id", session_key="s1")
    second = JobRequest(tool_name="get_replica_id", session_key="s1")

    assert first.job_id != second.job_id


def test_subjects_are_scoped_to_the_job() -> None:
    assert build_results_subject("abc") == "jobs.results.abc"
    assert build_answers_subject("abc") == "jobs.answers.abc"
    assert build_cancel_subject("abc") == "jobs.cancel.abc"

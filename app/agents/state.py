"""LangGraph shared state."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from app.schemas import (
    ApplicationResult,
    EmailSummary,
    ManualActionItem,
    MatchedJob,
    ResumeChunk,
    ResumeMetadata,
    UserProfile,
    JobListing,
)


def merge_lists(left: list, right: list) -> list:
    return left + right


class AgentState(TypedDict):
    run_id: str
    user_id: str
    resume_id: str
    resume_file_path: str

    user_profile: dict
    resume_chunks: list[dict]
    resume_metadata: dict

    jobs_found: Annotated[list[dict], merge_lists]
    matched_jobs: Annotated[list[dict], merge_lists]
    applied_jobs: Annotated[list[dict], merge_lists]
    pending_manual_jobs: Annotated[list[dict], merge_lists]
    failed_jobs: Annotated[list[dict], merge_lists]

    match_threshold: int
    max_applications_per_run: int
    applications_attempted: int

    next_agent: str
    application_complete: bool
    notification_sent: bool
    errors: Annotated[list[str], merge_lists]
    email_summary: dict | None
    email_status: str
    email_note: str
    email_log_path: str | None

    messages: Annotated[list, add_messages]

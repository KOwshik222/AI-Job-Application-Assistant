"""Pydantic schemas for API and agent state."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class UserProfile(BaseModel):
    role: str
    skills: list[str] = Field(default_factory=list)
    experience: int = 0
    locations: list[str] = Field(default_factory=list)
    email: EmailStr
    full_name: str = ""
    phone: str = ""


class ResumeChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: dict = Field(default_factory=dict)


class ResumeMetadata(BaseModel):
    extracted_skills: list[str] = Field(default_factory=list)
    experience_years: int | None = None
    projects: list[str] = Field(default_factory=list)


class JobListing(BaseModel):
    job_id: str = ""
    title: str
    company: str
    location: str = ""
    description: str = ""
    application_url: str
    source: str = "web"
    posted_at: str | None = None


class MatchedJob(JobListing):
    match_score: int = 0
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    match_rationale: str = ""


ApplicationStatus = Literal[
    "SUCCESS", "FAILED", "PENDING_MANUAL", "ELIGIBLE",
    "NOT_MATCHED", "QUEUED", "LLM_QUOTA_EXCEEDED", "IN_PROGRESS",
]
ManualStatus = Literal["PENDING_MANUAL_ACTION"]


class ApplicationResult(BaseModel):
    job_id: str
    company: str
    job_url: str
    status: ApplicationStatus
    resume_used: str
    applied_at: str | None = None
    error: str | None = None


class ManualActionItem(BaseModel):
    company: str
    job_url: str
    reason: str
    status: ManualStatus = "PENDING_MANUAL_ACTION"


class EmailSummary(BaseModel):
    applied_successfully: int = 0
    manual_action_required: int = 0
    failed: int = 0
    pending_manual_jobs: list[ManualActionItem] = Field(default_factory=list)
    applied_jobs: list[ApplicationResult] = Field(default_factory=list)
    run_id: str = ""


# --- API Request/Response ---


class UploadResumeResponse(BaseModel):
    user_id: str
    resume_id: str
    file_hash: str
    message: str
    chunks_indexed: int


class StartJobSearchRequest(BaseModel):
    user_id: str
    resume_id: str
    role: str
    skills: list[str] = Field(default_factory=list)
    experience: int = 0
    locations: list[str] = Field(default_factory=list)
    email: EmailStr
    full_name: str = ""
    phone: str = ""
    match_threshold: int | None = None
    max_applications: int | None = None


class StartJobSearchResponse(BaseModel):
    run_id: str
    status: str
    message: str


class ApplicationResponse(BaseModel):
    application_id: str
    company: str
    job_title: str
    status: str
    match_score: int | None
    applied_at: datetime | None
    job_url: str | None = None


class ApplicationsListResponse(BaseModel):
    applications: list[ApplicationResponse]
    total: int


class ManualActionResponse(BaseModel):
    action_id: str
    company: str
    url: str
    reason: str
    status: str


class ManualActionsListResponse(BaseModel):
    manual_actions: list[ManualActionResponse]


class ApplicationSummaryResponse(BaseModel):
    run_id: str
    status: str
    applied_successfully: int
    manual_action_required: int
    failed: int
    pending_manual_jobs: list[ManualActionItem]
    email_sent: bool
    email_status: str = "UNKNOWN"
    email_note: str = ""
    email_log_url: str | None = None
    jobs_found: int = 0
    matched_jobs: int = 0
    not_matched: int = 0
    queued: int = 0
    llm_quota_unprocessed: int = 0
    errors: list[str] = Field(default_factory=list)


class BrowserSessionResponse(BaseModel):
    browser_session_id: str
    application_url: str
    company: str
    job_title: str
    barrier_type: str
    status: str
    created_at: str


class BrowserSessionsListResponse(BaseModel):
    sessions: list[BrowserSessionResponse]


class ContinueApplicationRequest(BaseModel):
    browser_session_id: str


class ContinueApplicationResponse(BaseModel):
    status: str
    company: str = ""
    job_title: str = ""
    application_url: str = ""
    reason: str = ""
    confirmation: str = ""
    browser_session_id: str = ""


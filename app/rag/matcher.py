"""LLM-based resume-job matching via RAG with strict production error handling."""

import logging
from langchain_core.prompts import ChatPromptTemplate
from langsmith import traceable
from pydantic import BaseModel, Field

from app.config import get_settings
from app.rag.keyword_matcher import keyword_match_job
from app.rag.llm_provider import LLMProviderError, get_llm
from app.rag.vectorstore import get_resume_text, get_retriever
from app.schemas import JobListing, MatchedJob, UserProfile

logger = logging.getLogger(__name__)
settings = get_settings()


class MatchResult(BaseModel):
    job_title: str
    company: str
    match_score: int = Field(ge=0, le=100, description="Match score from 0 to 100")
    matching_skills: list[str] = Field(default_factory=list, description="Skills present in resume that match job requirements")
    missing_skills: list[str] = Field(default_factory=list, description="Skills required by job that are missing in resume")
    match_rationale: str = Field(description="Detailed evaluation based strictly on resume evidence")


MATCH_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert technical recruiter and resume-job matching AI. "
        "Your task is to evaluate how accurately a candidate's resume fits a specific job description.\n\n"
        "STRICT EVALUATION RULES:\n"
        "1. Base your evaluation ONLY on the provided resume excerpts and declared profile information.\n"
        "2. Score independently between 0 and 100 based on technical skill overlap, relevant experience, tools, and responsibilities.\n"
        "3. High match (75-100): Candidate meets core technical stack and experience level.\n"
        "4. Moderate match (50-74): Candidate has partial skill overlap or adjacent technologies.\n"
        "5. Low match (0-49): Significant skill or domain mismatch.\n"
        "6. List specific matching skills found in the resume, and specific missing skills required by the job.\n"
        "7. NEVER suggest modifying, tailoring, or rewriting the resume.",
    ),
    (
        "human",
        "Job Title: {title}\n"
        "Company: {company}\n"
        "Location: {location}\n\n"
        "Job Description:\n{description}\n\n"
        "Candidate Declared Skills: {skills}\n"
        "Candidate Experience (years): {experience}\n\n"
        "Relevant Resume Excerpts (RAG Retrieved):\n{resume_context}\n\n"
        "Evaluate this candidate against the job description and output the structured match result.",
    ),
])


@traceable(name="resume_job_match")
def match_job_to_resume(
    job: JobListing,
    resume_id: str,
    user_profile: UserProfile,
) -> MatchedJob:
    """Evaluate match score and rationale between job description and resume.
    
    In production mode: Uses configured LLM. If LLM fails, returns MATCHING_FAILED (never silently falls back).
    In demo mode: Clearly identified demo matcher.
    """
    if settings.is_demo_mode:
        logger.info("DEMO MODE: Evaluating match via demo keyword matcher.")
        resume_text = get_resume_text(resume_id)
        return keyword_match_job(job, user_profile, resume_text)

    try:
        retriever = get_retriever(resume_id, k=5)
        query = f"{job.title} {job.description} {' '.join(user_profile.skills)}"
        docs = retriever.invoke(query)
        resume_context = "\n---\n".join(d.page_content for d in docs)

        llm = get_llm(temperature=0.0)
        structured_llm = llm.with_structured_output(MatchResult)

        chain = MATCH_PROMPT | structured_llm
        result: MatchResult = chain.invoke({
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "description": job.description or "No description provided.",
            "skills": ", ".join(user_profile.skills),
            "experience": user_profile.experience,
            "resume_context": resume_context or "No specific resume excerpts retrieved.",
        })

        return MatchedJob(
            job_id=job.job_id,
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description,
            application_url=job.application_url,
            source=job.source,
            posted_at=job.posted_at,
            match_score=int(result.match_score),
            matching_skills=result.matching_skills,
            missing_skills=result.missing_skills,
            match_rationale=result.match_rationale,
        )
    except Exception as exc:
        # In production mode: NEVER silently fall back to keyword matching!
        logger.error("LLM matching failed in PRODUCTION mode for %s (%s): %s", job.company, job.title, exc)
        return MatchedJob(
            job_id=job.job_id,
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description,
            application_url=job.application_url,
            source=job.source,
            posted_at=job.posted_at,
            match_score=0,
            matching_skills=[],
            missing_skills=[],
            match_rationale=f"MATCHING_FAILED: LLM evaluation error ({exc}). Candidate will not be submitted.",
        )

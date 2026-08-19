"""LLM-based resume-job matching via RAG."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langsmith import traceable
from pydantic import BaseModel, Field

from app.config import get_settings
from app.rag.embeddings import is_demo_mode
from app.rag.keyword_matcher import keyword_match_job
from app.rag.vectorstore import get_resume_text, get_retriever
from app.schemas import JobListing, MatchedJob, UserProfile

settings = get_settings()


class MatchResult(BaseModel):
    job_title: str
    company: str
    match_score: int = Field(ge=0, le=100)
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    match_rationale: str = ""


MATCH_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a resume-job matching expert. Evaluate how well the candidate's resume "
        "matches a job description. Use ONLY the provided resume chunks for evidence. "
        "Never suggest modifying the resume. Return a score 0-100.",
    ),
    (
        "human",
        "Job Title: {title}\nCompany: {company}\nLocation: {location}\n\n"
        "Job Description:\n{description}\n\n"
        "Candidate declared skills: {skills}\nExperience (years): {experience}\n\n"
        "Relevant resume excerpts:\n{resume_context}\n\n"
        "Provide match_score, matching_skills, missing_skills, and match_rationale.",
    ),
])


@traceable(name="resume_job_match")
def match_job_to_resume(
    job: JobListing,
    resume_id: str,
    user_profile: UserProfile,
) -> MatchedJob:
    if is_demo_mode():
        resume_text = get_resume_text(resume_id)
        return keyword_match_job(job, user_profile, resume_text)

    retriever = get_retriever(resume_id, k=5)
    query = f"{job.title} {job.description} {' '.join(user_profile.skills)}"
    docs = retriever.invoke(query)
    resume_context = "\n---\n".join(d.page_content for d in docs)

    llm = ChatOpenAI(
        model=settings.chat_model,
        openai_api_key=settings.openai_api_key or None,
        temperature=0,
    ).with_structured_output(MatchResult)

    chain = MATCH_PROMPT | llm
    result: MatchResult = chain.invoke({
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "description": job.description,
        "skills": ", ".join(user_profile.skills),
        "experience": user_profile.experience,
        "resume_context": resume_context or "No resume context available.",
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
        match_score=result.match_score,
        matching_skills=result.matching_skills,
        missing_skills=result.missing_skills,
        match_rationale=result.match_rationale,
    )

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
    match_score: int = Field(ge=0, le=100, description="Overall calculated match score from 0 to 100")
    role_score: int = Field(default=0, ge=0, le=25, description="Role compatibility score out of 25")
    skills_score: int = Field(default=0, ge=0, le=30, description="Skills compatibility score out of 30")
    experience_score: int = Field(default=0, ge=0, le=20, description="Experience alignment score out of 20")
    projects_score: int = Field(default=0, ge=0, le=15, description="Projects relevance score out of 15")
    education_score: int = Field(default=0, ge=0, le=5, description="Education foundation score out of 5")
    other_score: int = Field(default=0, ge=0, le=5, description="Other requirements score out of 5")
    matching_skills: list[str] = Field(default_factory=list, description="Skills present in resume that match job requirements")
    missing_skills: list[str] = Field(default_factory=list, description="Skills required by job that are missing in resume")
    experience_required: str = Field(default="Not specified", description="Experience requirement stated in the job posting")
    match_rationale: str = Field(description="Detailed evaluation breakdown based strictly on resume evidence and projects")


MATCH_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert technical recruiter and resume-job matching AI. "
        "Your task is to evaluate how accurately a candidate's resume fits a specific job posting using a structured multi-criteria weighted scoring system.\n\n"
        "WEIGHTING CRITERIA (Total: 100 points):\n"
        "1. Role Compatibility (25% / 25 pts): Semantic role overlap. 'AI Developer' is compatible with AI Engineer, Machine Learning Engineer, ML Engineer, Generative AI Developer, GenAI Engineer, LLM Engineer, Junior AI Engineer, Python AI Developer, Applied AI Engineer.\n"
        "2. Skills Match (30% / 30 pts): Core technical stack overlap (Python, Machine Learning, Deep Learning, Generative AI, LLMs, LangChain, RAG, Computer Vision, NLP, PyTorch, TensorFlow, APIs). Evaluate overall capability; do not require every single peripheral keyword.\n"
        "3. Experience Alignment (20% / 20 pts): For candidates with 1-2 years experience, award full points (18-20 pts) for jobs accepting 0-1, 0-2, 1-2, 1+ years, or unspecified experience. Only penalize if the job explicitly mandates 3+, 4+, 5+ years or Senior/Lead/Staff level.\n"
        "4. Projects & Practical Work (15% / 15 pts): For entry/junior candidates, hands-on projects, GitHub repositories, capstones, and applied implementations in AI/ML/GenAI demonstrate strong practical ability and MUST contribute positively to this score.\n"
        "5. Education & Foundation (5% / 5 pts): CS, Engineering, Data Science, Math, or relevant technical degree/coursework.\n"
        "6. Other Relevant Requirements (5% / 5 pts): Git, Docker, Cloud, databases, clean code, agile practices.\n\n"
        "EVALUATION RULES:\n"
        "- Base your evaluation strictly on evidence in the resume text, project descriptions, and declared profile.\n"
        "- Calculate: match_score = role_score + skills_score + experience_score + projects_score + education_score + other_score.\n"
        "- High match (75-100): Candidate is eligible for application (meets core stack, relevant projects, and compatible experience).\n"
        "- Moderate match (50-74): Partial skill overlap or gaps in core requirements.\n"
        "- Low match (0-49): Significant domain or senior experience mismatch.\n"
        "- List specific matching skills found in the resume, and specific missing skills required by the job.\n"
        "- Do not hardcode scores or artificially inflate; evaluate accurately based on resume evidence.",
    ),
    (
        "human",
        "Job Title: {title}\n"
        "Company: {company}\n"
        "Location: {location}\n\n"
        "Job Description:\n{description}\n\n"
        "Candidate Declared Skills: {skills}\n"
        "Candidate Experience (years): {experience}\n\n"
        "Candidate Resume & Projects Context:\n{resume_context}\n\n"
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
        retriever = get_retriever(resume_id, k=6)
        query = f"{job.title} {job.description} {' '.join(user_profile.skills)} projects machine learning generative ai python"
        docs = retriever.invoke(query)
        rag_context = "\n---\n".join(d.page_content for d in docs)

        full_resume = get_resume_text(resume_id)
        if full_resume and len(full_resume) <= 4000:
            resume_context = full_resume
        else:
            resume_context = rag_context or (full_resume[:4000] if full_resume else "No resume content available.")

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
            "resume_context": resume_context,
        })

        calculated_score = int(result.match_score)
        # Prevent normalization drift
        calculated_score = max(0, min(100, calculated_score))

        return MatchedJob(
            job_id=job.job_id,
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description,
            application_url=job.application_url,
            source=job.source,
            posted_at=job.posted_at,
            match_score=calculated_score,
            matching_skills=result.matching_skills,
            missing_skills=result.missing_skills,
            match_rationale=result.match_rationale,
        )
    except Exception as exc:
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


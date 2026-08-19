"""Keyword-based resume-job matcher for demo mode (no OpenAI required)."""

from app.schemas import JobListing, MatchedJob, UserProfile


def keyword_match_job(
    job: JobListing,
    user_profile: UserProfile,
    resume_text: str = "",
) -> MatchedJob:
    jd = f"{job.title} {job.description} {job.location}".lower()
    resume_lower = resume_text.lower()

    matching_skills: list[str] = []
    for skill in user_profile.skills:
        sk = skill.lower()
        if sk in jd or sk in resume_lower:
            matching_skills.append(skill)

    common_reqs = [
        "aws", "docker", "kubernetes", "react", "angular", "python",
        "node", "azure", "gcp", "kafka", "redis", "mongodb",
    ]
    missing_skills: list[str] = []
    for req in common_reqs:
        if req in jd and not any(req in s.lower() for s in matching_skills):
            label = req.upper() if len(req) <= 3 else req.title()
            if label not in missing_skills:
                missing_skills.append(label)

    role_words = user_profile.role.lower().split()
    role_hits = sum(1 for w in role_words if len(w) > 2 and w in jd)

    score = 40
    score += len(matching_skills) * 8
    score += role_hits * 5
    if user_profile.experience >= 2:
        score += 10
    if any(loc.lower() in jd for loc in user_profile.locations):
        score += 10
    score = min(100, score)

    rationale = (
        f"Demo mode: {len(matching_skills)} skills match job requirements. "
        f"Role alignment: {role_hits} keywords. "
        f"Experience: {user_profile.experience} years."
    )

    return MatchedJob(
        job_id=job.job_id,
        title=job.title,
        company=job.company,
        location=job.location,
        description=job.description,
        application_url=job.application_url,
        source=job.source,
        posted_at=job.posted_at,
        match_score=score,
        matching_skills=matching_skills,
        missing_skills=missing_skills[:5],
        match_rationale=rationale,
    )

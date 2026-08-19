"""Resume upload endpoint."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.repository import Repository
from app.rag.loader import load_and_chunk_resume
from app.rag.vectorstore import index_resume_chunks
from app.schemas import UploadResumeResponse
from app.services.resume_storage import store_resume_pdf

router = APIRouter(prefix="/api/v1", tags=["resume"])


@router.post("/upload-resume", response_model=UploadResumeResponse)
async def upload_resume(
    file: UploadFile = File(...),
    email: str = Form(...),
    session: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF resumes are accepted")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    repo = Repository(session)
    user = await repo.get_or_create_user(email)
    resume_id, file_path, file_hash = await store_resume_pdf(content, user.user_id)

    existing = await repo.get_resume_by_hash(user.user_id, file_hash)
    if existing:
        chunks = load_and_chunk_resume(existing.file_path)
        index_resume_chunks(existing.resume_id, chunks)
        await repo.commit()
        return UploadResumeResponse(
            user_id=user.user_id,
            resume_id=existing.resume_id,
            file_hash=existing.file_hash,
            message="Resume already on file (unchanged). RAG re-indexed.",
            chunks_indexed=len(chunks),
        )

    resume = await repo.create_resume(user.user_id, file_path, file_hash)
    resume_id = resume.resume_id

    chunks = load_and_chunk_resume(file_path)
    index_resume_chunks(resume_id, chunks)
    await repo.commit()

    return UploadResumeResponse(
        user_id=user.user_id,
        resume_id=resume_id,
        file_hash=file_hash,
        message="Resume stored unchanged. RAG indexing complete.",
        chunks_indexed=len(chunks),
    )

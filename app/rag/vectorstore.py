"""Vector store and retriever for resume understanding."""

from langchain_chroma import Chroma
from langchain_core.documents import Document
from app.config import get_settings
from app.rag.embeddings import get_embeddings
from app.schemas import ResumeChunk

settings = get_settings()


def index_resume_chunks(resume_id: str, chunks: list[ResumeChunk]) -> Chroma:
    docs = [
        Document(
            page_content=c.content,
            metadata={"chunk_id": c.chunk_id, "resume_id": resume_id, **c.metadata},
        )
        for c in chunks
    ]
    vectorstore = Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        collection_name=f"resume_{resume_id}",
        persist_directory=str(settings.data_dir / "chroma"),
    )
    return vectorstore


def get_retriever(resume_id: str, k: int = 5):
    vectorstore = Chroma(
        collection_name=f"resume_{resume_id}",
        embedding_function=get_embeddings(),
        persist_directory=str(settings.data_dir / "chroma"),
    )
    return vectorstore.as_retriever(search_kwargs={"k": k})


def get_resume_text(resume_id: str) -> str:
    try:
        vectorstore = Chroma(
            collection_name=f"resume_{resume_id}",
            embedding_function=get_embeddings(),
            persist_directory=str(settings.data_dir / "chroma"),
        )
        data = vectorstore.get()
        docs = data.get("documents") or []
        return "\n".join(docs)
    except Exception:
        return ""

"""PDF loading and chunking for RAG (understanding only)."""

import uuid
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.schemas import ResumeChunk


def load_and_chunk_resume(pdf_path: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[ResumeChunk]:
    loader = PyPDFLoader(pdf_path)
    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    splits = splitter.split_documents(documents)

    chunks: list[ResumeChunk] = []
    for i, doc in enumerate(splits):
        chunks.append(
            ResumeChunk(
                chunk_id=str(uuid.uuid4()),
                content=doc.page_content,
                metadata={"page": doc.metadata.get("page", i), "source": Path(pdf_path).name},
            )
        )
    return chunks

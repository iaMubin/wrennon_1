"""
One-off ingestion script. Run manually whenever policy_docs/ changes:

    python scripts/ingest.py

Parses PDFs page-by-page with PyMuPDF (fitz) and chunks with
RecursiveCharacterTextSplitter, which respects paragraph/sentence
boundaries instead of cutting mid-sentence — this is the pipeline
carried over from the prior working RAG build, after the naive
word-count chunker here produced junk chunks (page headers/nav text
fused into policy content) that tanked Cohere relevance scores.

Re-running clears and rebuilds the collection rather than appending,
so stale chunks never linger.

Embeddings are computed via Cohere's API (embed-english-v3.0) instead
of a local sentence-transformers model — keeps RAM under 512 MB for
Render's free tier.
"""

from __future__ import annotations

import sys
from pathlib import Path

import uuid
from pinecone import Pinecone
import fitz
from langchain_text_splitters import RecursiveCharacterTextSplitter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402
from app.services.cohere_embeddings import CohereEmbedder  # noqa: E402

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ".", " ", ""],
)


def parse_pdf(path: Path) -> str:
    doc = fitz.open(path)
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n\n".join(pages)


def load_documents(docs_dir: Path) -> list[str]:
    chunks: list[str] = []
    for path in docs_dir.glob("*.pdf"):
        full_text = parse_pdf(path)
        chunks.extend(_splitter.split_text(full_text))
    for path in docs_dir.glob("*.txt"):
        chunks.extend(_splitter.split_text(path.read_text(encoding="utf-8")))
    return chunks


def main() -> None:
    docs_dir = Path(__file__).resolve().parent.parent / "data" / "policy_docs"
    if not docs_dir.exists() or not any(docs_dir.iterdir()):
        print(f"No source documents found in {docs_dir}. Add .pdf or .txt files first.")
        return

    chunks = load_documents(docs_dir)
    print(f"Loaded {len(chunks)} chunks from {docs_dir}")

    cohere_ef = CohereEmbedder(
        api_key=settings.cohere_api_key,
        model_name="embed-english-v3.0",
    )

    pinecone = Pinecone(api_key=settings.pinecone_api_key)
    index = pinecone.Index(host=settings.pinecone_host)
    
    # We delete all existing vectors before re-ingesting to avoid stale chunks.
    # We do this by deleting the index or just calling delete_all?
    # Pinecone delete all: index.delete(delete_all=True)
    try:
        index.delete(delete_all=True)
    except Exception as e:
        print(f"Warning on delete all (can be ignored on empty index): {e}")

    # Compute embeddings
    print("Computing embeddings via Cohere...")
    embeddings = cohere_ef.embed_documents(chunks)

    # Upsert in batches
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i:i + batch_size]
        batch_embeddings = embeddings[i:i + batch_size]
        
        vectors = []
        for j, (chunk, embedding) in enumerate(zip(batch_chunks, batch_embeddings)):
            # Convert numpy floats to standard python floats if necessary
            if hasattr(embedding, "tolist"):
                embedding = embedding.tolist()
            else:
                embedding = [float(x) for x in embedding]
            
            vectors.append({
                "id": f"chunk-{i+j}",
                "values": embedding,
                "metadata": {"text": chunk}
            })
            
        index.upsert(vectors=vectors)

    print(f"Ingested {len(chunks)} chunks into Pinecone index at {settings.pinecone_host}")


if __name__ == "__main__":
    main()

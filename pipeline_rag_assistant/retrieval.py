"""
Retrieval — same BM25(0.7)/dense(0.3) exact-match-first weighting as
every version of this we've built. Generalized here: the embedding
PROVIDER is selectable, not hardcoded, so users without an OpenAI key
can run this fully free/local (Hugging Face), and users who want
OpenAI's embeddings can use those instead -- same interface either way.
"""

from __future__ import annotations

import os

from langchain_chroma import Chroma
from langchain_classic.retrievers.ensemble import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

CANDIDATE_K = 6


def _build_embeddings(provider: str):
    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model="text-embedding-3-small")

    if provider == "huggingface":
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

    raise ValueError(f"Unknown embed provider: {provider!r} (expected 'openai' or 'huggingface')")


def build_retriever(blocks: list[Document], embed_provider: str | None = None):
    embed_provider = embed_provider or os.environ.get("PIPELINE_RAG_EMBED_PROVIDER", "huggingface")

    bm25_retriever = BM25Retriever.from_documents(blocks)
    bm25_retriever.k = CANDIDATE_K

    embeddings = _build_embeddings(embed_provider)
    vectorstore = Chroma.from_documents(blocks, embeddings)
    dense_retriever = vectorstore.as_retriever(search_kwargs={"k": CANDIDATE_K})

    return EnsembleRetriever(retrievers=[bm25_retriever, dense_retriever], weights=[0.7, 0.3])

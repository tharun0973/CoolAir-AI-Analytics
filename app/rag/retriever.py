"""
CoolAir Comfort Services — Retriever
========================================
Loads the FAISS index built by app/rag/build_vector_store.py and answers
document-grounded questions with source attribution.

Two responsibilities, kept separate:
  1. retrieve(question) — pure retrieval, no LLM call, ranks chunks by
     embedding similarity with a priority tie-break (v2 addendum outranks
     v1 handbook on close matches, since it's the more current source).
  2. generate_answer(question) — retrieval + LLM synthesis, grounding the
     answer strictly in retrieved chunks and citing which document/version
     it came from. This is the piece that needs an API key.

Usage:
    from app.retriever import Retriever
    r = Retriever()
    r.load()
    chunks = r.retrieve("What is the emergency diagnostic fee?")
    answer = r.generate_answer("What is the emergency diagnostic fee?")
"""

import json
from pathlib import Path

from groq import Groq

from app.utils.config import (
    VECTOR_INDEX_PATH,
    VECTOR_CHUNKS_PATH,
    EMBEDDING_MODEL,
    RAG_TOP_K,
    GROQ_API_KEY,
    LLM_MODEL,
    require_llm_key,
)

ANSWER_SYSTEM_PROMPT = """You answer questions about CoolAir Comfort Services' pricing and
policies using ONLY the provided context chunks. Rules:
- If sources conflict, prefer the chunk with the later effective_date, unless the
  question is clearly asking about a past date/order — in that case use whichever
  source's effective_date applies as of that date.
- Never state a figure that isn't in the provided context.
- End your answer with: "Source: <document name>, effective <date>."
- If the context doesn't contain the answer, say so plainly rather than guessing.
"""


class Retriever:
    def __init__(
        self,
        index_path: Path = VECTOR_INDEX_PATH,
        chunks_path: Path = VECTOR_CHUNKS_PATH,
        model_name: str = EMBEDDING_MODEL,
    ):
        self.index_path = index_path
        self.chunks_path = chunks_path
        self.model_name = model_name
        self._model = None
        self._index = None
        self._chunks = None
        self._metadata = None

    def load(self):
        """
        Loads the embedding model and the prebuilt FAISS index + chunk
        metadata. Requires app/rag/build_vector_store.py to have been run
        first (needs network access for the embedding model download).
        """
        if not self.index_path.exists() or not self.chunks_path.exists():
            raise FileNotFoundError(
                f"Vector index not found at {self.index_path}. "
                f"Run app/rag/build_vector_store.py first."
            )

        import faiss
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_name)
        self._index = faiss.read_index(str(self.index_path))

        with open(self.chunks_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._chunks = data["chunks"]
        self._metadata = data["metadata"]

        return self

    def _ensure_loaded(self):
        if self._index is None:
            raise RuntimeError("Retriever not loaded. Call .load() first.")

    def retrieve(self, question: str, k: int = RAG_TOP_K) -> list:
        """
        Returns the top-k chunks by embedding similarity, re-sorted so that
        among comparably close matches, the higher-priority (more current)
        source ranks first.
        """
        self._ensure_loaded()

        import numpy as np

        q_emb = self._model.encode([question]).astype("float32")
        distances, indices = self._index.search(q_emb, k)

        results = []

        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue

            results.append(
                {
                    "chunk": self._chunks[idx],
                    "metadata": self._metadata[idx],
                    "distance": float(dist),
                }
            )

        results.sort(
            key=lambda r: (
                round(r["distance"], 1),
                -r["metadata"]["priority"],
            )
        )

        return results

    def format_context(self, results: list) -> str:
        """Formats retrieved chunks into a labeled block for the LLM prompt."""
        parts = []

        for r in results:
            m = r["metadata"]

            parts.append(
                f"[Source: {m['source']}, version={m['version']}, "
                f"effective_date={m['effective_date']}]\n{r['chunk']}"
            )

        return "\n\n---\n\n".join(parts)
    def generate_answer(self, question: str, k: int = RAG_TOP_K) -> dict:
        """
        Full RAG answer: retrieve + LLM synthesis grounded in the retrieved
        context.
        """
        require_llm_key()

        results = self.retrieve(question, k=k)
        context = self.format_context(results)

        client = Groq(api_key=GROQ_API_KEY)

        response = client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            max_tokens=400,
            messages=[
                {
                    "role": "system",
                    "content": ANSWER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion:\n{question}",
                },
            ],
        )

        answer = response.choices[0].message.content.strip()

        return {
            "question": question,
            "context": context,
            "answer": answer,
            "sources": [r["metadata"] for r in results],
        }


if __name__ == "__main__":
    # Retrieval-only smoke test (still needs the index built + network for
    # the embedding model — see app/rag/build_vector_store.py). Uncomment
    # to run once you have internet access:
    #
    # r = Retriever().load()
    # for q in [
    #     "What is the emergency diagnostic fee?",
    #     "What is the parts warranty on a compressor?",
    # ]:
    #     print(f"\nQ: {q}")
    #     for res in r.retrieve(q, k=2):
    #         m = res["metadata"]
    #         print(f"  [{m['version']}, {m['effective_date']}] {res['chunk'][:100]}...")
    #
    # To test answer generation:
    #
    # r = Retriever().load()
    # print(r.generate_answer("What is the emergency diagnostic fee?"))

    print(
        "Retriever module loaded successfully. Uncomment the block above "
        "to run a live retrieval or RAG test once "
        "app/rag/build_vector_store.py has been run."
    )
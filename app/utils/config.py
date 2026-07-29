"""
CoolAir Comfort Services — Central Config
=============================================
Single source of truth for paths, environment variables, and tunable
constants used across app/retriever.py, app/chatbot.py, and the numbered
pipeline scripts. Import from here instead of hardcoding paths or magic
numbers in multiple files.

Reads secrets from a .env file at the project root (never commit this —
see .env.example for the expected keys) via python-dotenv, falling back
to actual environment variables if no .env is present.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR = BASE_DIR / "data"
CLEANED_DATA_DIR = BASE_DIR / "cleaned_data"
DOCUMENTS_DIR = BASE_DIR / "documents"
DATABASE_DIR = BASE_DIR / "database"
LOGS_DIR = BASE_DIR / "logs"
SCRIPTS_DIR = BASE_DIR / "scripts"

DB_PATH = DATABASE_DIR / "coolair.db"
VECTOR_INDEX_PATH = DATABASE_DIR / "policy_index.faiss"
VECTOR_CHUNKS_PATH = DATABASE_DIR / "policy_chunks.json"
ROUTING_LOG_PATH = LOGS_DIR / "routing_log.jsonl"

# ------------------------------------------------------------------
# Environment Variables
# ------------------------------------------------------------------

load_dotenv(BASE_DIR / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "llama-3.3-70b-versatile"
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "all-MiniLM-L6-v2"
)

# ------------------------------------------------------------------
# Tunable Constants
# ------------------------------------------------------------------

ROUTER_AMBIGUOUS_GAP = 2

RAG_TOP_K = 4
RAG_CHUNK_SIZE_CHARS = 600
RAG_CHUNK_OVERLAP_CHARS = 100

SQL_QUERY_TIMEOUT_SECONDS = 10

# ------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------


def has_llm_key() -> bool:
    """Returns True if the Groq API key is configured."""
    return bool(GROQ_API_KEY)


def require_llm_key():
    """Raises a clear error if no Groq API key is configured."""
    if not has_llm_key():
        raise RuntimeError(
            "No GROQ_API_KEY configured. Please add it to your .env file."
        )


# ------------------------------------------------------------------
# Self Test
# ------------------------------------------------------------------

if __name__ == "__main__":

    print("BASE_DIR:", BASE_DIR)

    for name, path in [
        ("DATA_DIR", DATA_DIR),
        ("CLEANED_DATA_DIR", CLEANED_DATA_DIR),
        ("DOCUMENTS_DIR", DOCUMENTS_DIR),
        ("DB_PATH", DB_PATH),
        ("VECTOR_INDEX_PATH", VECTOR_INDEX_PATH),
        ("LOGS_DIR", LOGS_DIR),
    ]:
        print(f"{name}: {path} [{'exists' if path.exists() else 'MISSING'}]")

    print(f"\nLLM_PROVIDER: {LLM_PROVIDER}")
    print(f"LLM_MODEL: {LLM_MODEL}")
    print(f"API key configured: {has_llm_key()}")
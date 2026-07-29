"""
CoolAir Comfort Services — Query Router
========================================
Routes a user's question to one of three pipelines:

1. SQL
2. RAG
3. HYBRID (SQL + RAG)

The router is intentionally rule-based. It is deterministic, easy to
explain in an interview, and can later be replaced with an LLM router.
"""

import re
from enum import Enum


class RouteType(Enum):
    SQL = "sql"
    RAG = "rag"
    HYBRID = "hybrid"


SQL_KEYWORDS = {
    "customer", "customers",
    "invoice", "invoices",
    "technician", "technicians",
    "order", "orders",
    "revenue", "sales",
    "count", "average",
    "total", "sum",
    "highest", "lowest",
    "top", "bottom",
    "profit",
    "amount",
    "paid", "unpaid",
    "jobs",
    "completed",
    "cancelled",
}

RAG_KEYWORDS = {
    "policy",
    "pricing",
    "price",
    "refund",
    "warranty",
    "guarantee",
    "manual",
    "sop",
    "procedure",
    "document",
    "service agreement",
    "maintenance",
    "compressor",
    "diagnostic",
    "inspection",
    "emergency",
    "replacement",
    "coverage",
}


class Router:
    """Routes a user question to SQL, RAG or Hybrid."""

    @staticmethod
    def normalize(text: str) -> str:
        text = text.lower()
        return re.sub(r"[^\w\s]", " ", text)

    @staticmethod
    def calculate_scores(question: str):
        sql_score = sum(1 for word in SQL_KEYWORDS if word in question)
        rag_score = sum(1 for word in RAG_KEYWORDS if word in question)
        return sql_score, rag_score

    def route(self, question: str) -> dict:
        question = self.normalize(question)

        sql_score, rag_score = self.calculate_scores(question)

        if sql_score > 0 and rag_score > 0:
            route = RouteType.HYBRID
        elif sql_score > 0:
            route = RouteType.SQL
        elif rag_score > 0:
            route = RouteType.RAG
        else:
            route = RouteType.RAG

        return {
            "route": route,
            "sql_score": sql_score,
            "rag_score": rag_score,
        }


if __name__ == "__main__":
    router = Router()

    questions = [
        "How many customers do we have?",
        "Show revenue by technician",
        "What is the compressor warranty?",
        "What is the emergency diagnostic fee?",
        "How much revenue did emergency repairs generate under the new pricing policy?",
        "Explain the refund policy",
        "List all cancelled orders",
        "How many maintenance jobs were completed?",
    ]

    print("=== Router Test ===\n")

    for q in questions:
        result = router.route(q)
        print(f"{result['route'].value.upper():8} -> {q}")
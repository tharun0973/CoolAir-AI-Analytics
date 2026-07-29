"""
CoolAir Comfort Services - Chatbot

Central orchestrator for the AI Analytics Assistant.

Responsibilities:
- Accept user questions
- Route the question (SQL / RAG / Hybrid)
- Call the appropriate module
- Return a structured response

Author: Tharun Kumar
"""

from groq import Groq

from app.router.router import Router, RouteType
from app.sql.sql_agent import SQLAgent
from app.rag.retriever import Retriever
from app.utils.config import GROQ_API_KEY, LLM_MODEL


class Chatbot:
    """Main chatbot orchestrator."""

    def __init__(self):
        self.router = Router()
        self.sql_agent = SQLAgent()
        self.retriever = Retriever().load()

    def ask(self, question: str) -> dict:
        """
        Process a user question.

        Returns:
            {
                "route": "...",
                "answer": "...",
                "sources": [...]
            }
        """

        decision = self.router.route(question)
        route = decision["route"]

        # ---------------- SQL ---------------- #

        if route == RouteType.SQL:

            result = self.sql_agent.answer_question(question)

            return {
                "route": "SQL",
                "answer": result,
                "sources": []
            }

        # ---------------- RAG ---------------- #

        elif route == RouteType.RAG:

            result = self.retriever.generate_answer(question)

            return {
                "route": "RAG",
                "answer": result["answer"],
                "sources": result["sources"]
            }

        # ---------------- Hybrid ---------------- #

        elif route == RouteType.HYBRID:

            sql_result = self.sql_agent.answer_question(question)

            rag_result = self.retriever.generate_answer(question)

            client = Groq(api_key=GROQ_API_KEY)

            response = client.chat.completions.create(
                model=LLM_MODEL,
                temperature=0,
                max_tokens=400,
                messages=[
                    {
                        "role": "system",
                        "content": """
You are a business analytics assistant for CoolAir Comfort Services.

Answer using BOTH sources:

1. Database Result:
- Explain what calculation was performed.
- Mention assumptions such as billed revenue vs collected revenue.
- Do not change numbers returned from SQL.

2. Policy Context:
- Use the policy documents to explain pricing, rules, or business context.
- If documents conflict, prefer the document with the latest effective date.
- Mention the effective date when relevant.

Rules:
- Do not ignore either source.
- Do not invent information outside the provided sources.
- Give a concise business-friendly answer.
"""
                    },
                    {
                        "role": "user",
                        "content": f"""
Question:
{question}

Database Result:
{sql_result}

Policy Context:
{rag_result["context"]}
"""
                    },
                ],
            )

            final_answer = response.choices[0].message.content.strip()

            return {
                "route": "HYBRID",
                "answer": final_answer,
                "sources": rag_result["sources"]
            }


if __name__ == "__main__":

    bot = Chatbot()

    print("\nCoolAir AI Assistant")
    print("-----------------------------")

    while True:

        question = input("\nYou: ")

        if question.lower() in ("exit", "quit"):
            break

        response = bot.ask(question)

        print(f"\nRoute : {response['route']}")
        print(f"\nAnswer:\n{response['answer']}")
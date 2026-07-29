"""
CoolAir Comfort Services - FastAPI API

Exposes the AI Analytics Assistant as REST endpoints.

Endpoints
---------
GET  /                 -> Welcome message
GET  /health           -> Health check
POST /ask              -> Ask the AI assistant

Author: Tharun Kumar
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.chatbot.chatbot import Chatbot

app = FastAPI(
    title="CoolAir AI Analytics Assistant",
    description="Hybrid SQL + RAG Question Answering System",
    version="1.0.0",
)

# ----------------------------------------------------
# Initialize Chatbot
# ----------------------------------------------------

chatbot = None
startup_error = None

try:
    chatbot = Chatbot()
except Exception as e:
    startup_error = str(e)


# ----------------------------------------------------
# Request Model
# ----------------------------------------------------

class QuestionRequest(BaseModel):
    question: str


# ----------------------------------------------------
# Routes
# ----------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "CoolAir AI Analytics Assistant is running.",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "chatbot_loaded": chatbot is not None,
        "version": "1.0.0"
    }


@app.post("/ask")
def ask(request: QuestionRequest):
    """
    Main Question Answering Endpoint
    """

    if chatbot is None:
        raise HTTPException(
            status_code=500,
            detail=f"Chatbot failed to initialize: {startup_error}"
        )

    # Validate empty question
    if not request.question.strip():
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    try:
        response = chatbot.ask(request.question)
        return response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ----------------------------------------------------
# Run locally
# ----------------------------------------------------

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
"""
CoolAir AI Analytics Assistant - Chainlit Interface

Conversational AI layer for:
- SQL Analytics
- RAG Document Retrieval
- Hybrid Reasoning
"""

import chainlit as cl

from app.chatbot.chatbot import Chatbot


# Initialize chatbot
bot = Chatbot()


@cl.on_chat_start
async def start():

    await cl.Message(
        content="""
# 👋 CoolAir AI Analytics Assistant

Ask questions about:

📊 Revenue & Customers  
🔧 Service Operations  
👨‍🔧 Technician Performance  
📄 Pricing & Policies  

Powered by:
- SQL Analytics
- RAG Document Retrieval
- Hybrid Reasoning
        """
    ).send()

@cl.on_message
async def main(message: cl.Message):

    question = message.content

    response = bot.ask(question)

    route = response.get("route", "")
    answer = response.get("answer")
    sources = response.get("sources", [])


    # -------------------------
    # Format SQL responses
    # -------------------------

    if isinstance(answer, dict):

        if "results" in answer:

            results = answer.get("results", [])

            if results and isinstance(results, list):

                value = list(results[0].values())[0]

                answer = f"""
## 📊 Business Analysis

**Result:**
{value}

**Data Source:**
Operational Database
"""

            else:
                answer = "No results found."

        else:
            answer = str(answer)


    # -------------------------
    # Route explanation
    # -------------------------

    route_text = {

        "SQL": """
### Analysis Type
🗄️ SQL Analytics

Used structured operational data to answer this question.
""",

        "RAG": """
### Analysis Type
📄 Document Retrieval (RAG)

Used company policy documents to answer this question.
""",

        "HYBRID": """
### Analysis Type
🔀 Hybrid Reasoning

Combined:
- Database analysis
- Business document context
"""
    }


    output = f"""
{answer}

---

{route_text.get(route, route)}
"""


    # -------------------------
    # Clean source display
    # -------------------------

    if sources:

        unique_sources = {}

        for source in sources:

            if isinstance(source, dict):

                name = source.get("source")

                date = source.get("effective_date")

                unique_sources[name] = date


        output += """

---

### 📚 Sources

"""


        for name, date in unique_sources.items():

            if date:
                output += f"📄 {name}  \nEffective date: {date}\n\n"

            else:
                output += f"📄 {name}\n\n"


    await cl.Message(
        content=output
    ).send()
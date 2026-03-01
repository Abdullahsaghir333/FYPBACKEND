from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.config import settings


llm = ChatGoogleGenerativeAI(
    model=settings.gemini_model,
    api_key=settings.gemini_api_key,
    temperature=0.4,
)

__all__ = ["llm"]


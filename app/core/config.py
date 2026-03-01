import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    app_name: str = "AI Teacher Backend"
    api_v1_prefix: str = "/api"
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash-lite"
    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in the environment.")
    return Settings(gemini_api_key=api_key)


settings = get_settings()


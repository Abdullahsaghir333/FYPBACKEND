import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel


load_dotenv()


class Settings(BaseModel):
    app_name: str = "Acadomi AI Backend"
    api_v1_prefix: str = "/api"
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash-lite"
    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    mongodb_uri: str = "mongodb://localhost:27017/acadomi"
    jwt_secret: str = "fallback_dev_secret"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in the environment.")
    return Settings(
        gemini_api_key=api_key,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        mongodb_uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017/acadomi"),
        jwt_secret=os.getenv("JWT_SECRET", "fallback_dev_secret"),
    )


settings = get_settings()


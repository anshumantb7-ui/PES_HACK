import os
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseModel):
    PROJECT_NAME: str = "RESQ Command Backend"
    HOST: str = os.getenv("RESQ_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("RESQ_PORT", "8000"))
    
    # Secret header token expected from Phone B forwarder app
    # Can be provided in 'X-RESQ-Secret' or 'Authorization: Bearer <secret>'
    SECRET_TOKEN: str = os.getenv("RESQ_SECRET_TOKEN", "resq-secret-key-2026")
    
    # Database URL: defaults to PostgreSQL, falls back to SQLite if unreachable
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql+psycopg://postgres:postgres@localhost:5432/resq"
    )
    SQLITE_FALLBACK_URL: str = f"sqlite:///{BASE_DIR / 'resq.db'}"
    
    # Gemini API key for parser fallback on low-confidence messages
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Deduplication time window in seconds (default 5 minutes)
    DEDUP_WINDOW_SECONDS: int = int(os.getenv("DEDUP_WINDOW_SECONDS", "300"))

settings = Settings()


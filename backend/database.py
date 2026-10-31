import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.config import settings

logger = logging.getLogger("resq.database")

Base = declarative_base()

def get_engine():
    """Attempts to connect to configured DATABASE_URL (e.g. PostgreSQL),
    falls back to SQLite if unreachable or not configured.
    """
    db_url = settings.DATABASE_URL
    if "postgres" in db_url.lower():
        try:
            # Psycopg3 accepts connect_timeout in connect_args
            engine = create_engine(
                db_url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 2},
            )
            with engine.connect():
                logger.info(f"Connected to primary database: {db_url.split('@')[-1] if '@' in db_url else db_url}")
                return engine, "postgresql"
        except Exception as e:
            logger.info(
                f"PostgreSQL not reachable ({e}). "
                f"Using local SQLite at {settings.SQLITE_FALLBACK_URL}"
            )
            sqlite_engine = create_engine(
                settings.SQLITE_FALLBACK_URL, 
                connect_args={"check_same_thread": False}
            )
            return sqlite_engine, "sqlite"
    else:
        sqlite_engine = create_engine(
            settings.SQLITE_FALLBACK_URL, 
            connect_args={"check_same_thread": False}
        )
        return sqlite_engine, "sqlite"

engine, DB_KIND = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

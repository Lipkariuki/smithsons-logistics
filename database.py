import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def _build_database_url() -> str:
    # Prefer env vars
    url = (
        os.getenv("DATABASE_URL")
        or os.getenv("SQLALCHEMY_DATABASE_URL")
        or ""
    )
    if not url:
        # Fallback to previous dev default (not recommended for prod)
        url = "postgresql+psycopg://postgres:password@localhost:5432/postgres"

    # Ensure SQLAlchemy driver prefix
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    # Ensure sslmode=require if not present and env hints demand it
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    if "sslmode" not in q and os.getenv("REQUIRE_DB_SSL", "true").lower() in ("1", "true", "yes"): 
        q["sslmode"] = ["require"]
    new_query = urlencode({k: v[0] if isinstance(v, list) else v for k, v in q.items()})
    url = urlunparse(parsed._replace(query=new_query))
    return url


SQLALCHEMY_DATABASE_URL = _build_database_url()

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

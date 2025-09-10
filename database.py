from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Railway PostgreSQL connection
SQLALCHEMY_DATABASE_URL = "postgresql+psycopg://postgres:kRjxXXjYpWJyFPkVpqPIRCSZAJgRPIwG@maglev.proxy.rlwy.net:11266/railway"

# Create engine and session
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

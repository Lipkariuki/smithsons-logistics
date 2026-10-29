from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from settings import database_url

SQLALCHEMY_DATABASE_URL = database_url()

# Creating the engine does not connect. Never log SQL authentication parameters.
engine = create_engine(SQLALCHEMY_DATABASE_URL, echo=False, hide_parameters=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

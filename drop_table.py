# drop_table.py
from sqlalchemy import text
from database import engine

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS orders CASCADE;"))
    print("✅ Dropped orders table.")

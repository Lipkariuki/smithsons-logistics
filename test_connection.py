from database import SessionLocal
from sqlalchemy import text


def test_connection():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))  # ✅ fix wrapped with text()
        print("✅ Connection to Supabase PostgreSQL is successful!")
    except Exception as e:
        print("❌ Failed to connect:", e)
    finally:
        db.close()


if __name__ == "__main__":
    test_connection()

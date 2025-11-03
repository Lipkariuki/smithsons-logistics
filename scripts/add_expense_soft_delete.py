"""
Utility script to add the `is_deleted` column to the expenses table if it does not exist.
Run once after deploying the updated models.
"""

from sqlalchemy import inspect, text

from database import engine


def ensure_is_deleted_column() -> None:
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("expenses")}
    if "is_deleted" in columns:
        print("Column `is_deleted` already exists on expenses.")
        return

    ddl = text("ALTER TABLE expenses ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE")
    backfill = text("UPDATE expenses SET is_deleted = FALSE WHERE is_deleted IS NULL")
    with engine.begin() as conn:
        conn.execute(ddl)
        conn.execute(backfill)
    print("Column `is_deleted` added and initialised to FALSE.")


if __name__ == "__main__":
    ensure_is_deleted_column()

# create_tables.py

from database import Base, engine
from models import *

# 🚨 Drop everything first
Base.metadata.drop_all(bind=engine)

# ✅ Recreate from updated models
Base.metadata.create_all(bind=engine)

print("✅ All tables dropped and recreated successfully.")

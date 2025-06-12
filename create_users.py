# # # create_admin.py

# from sqlalchemy.orm import Session
# from passlib.context import CryptContext
# from database import SessionLocal
# from models import User

# # # Setup password hasher
# # pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# # def hash_password(password: str) -> str:
# #     return pwd_context.hash(password)


# # def create_admin():
# #     db: Session = SessionLocal()

# #     try:
# #         existing_admin = db.query(User).filter(User.role == "admin").first()
# #         if existing_admin:
# #             print("⚠️ Admin already exists.")
# #             return

# #         new_admin = User(
# #             name="Super Admin",
# #             phone="0756123456",
# #             password_hash=hash_password("adminpass123"),
# #             role="admin"
# #         )
# #         db.add(new_admin)
# #         db.commit()
# #         db.refresh(new_admin)

# #         print("✅ Admin user created!")
# #         print(f"Phone: {new_admin.phone}")
# #         print(f"Password: adminpass123")
# #     except Exception as e:
# #         db.rollback()
# #         print("❌ Failed to create admin:", str(e))
# #     finally:
# #         db.close()


# #drivers

# from passlib.context import CryptContext

# # Initialize the password hashing context
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# # Create a new database session
# db = SessionLocal()

# # Define dummy driver data with full_name and phone
# dummy_drivers = [
#     {"full_name": "James Kariuki", "phone": "0701000001"},
#     {"full_name": "Mercy Wanjiku", "phone": "0701000002"},
#     {"full_name": "Brian Otieno", "phone": "0701000003"},
# ]

# # Iterate over each driver and create a User instance
# for driver in dummy_drivers:
#     # Generate a unique email for each driver
#     email_username = driver["full_name"].lower().replace(" ", ".")
#     email = f"{email_username}@example.com"

#     # Hash the password for security
#     hashed_pw = pwd_context.hash("driverpass123")

#     # Create a new User instance
#     user = User(
#         name=driver["full_name"],
#         email=email,
#         phone=driver["phone"],
#         password_hash=hashed_pw,
#         role="driver"
#     )

#     # Add the user to the session
#     db.add(user)

# # Commit the session to save the users to the database
# db.commit()

# # Close the session
# db.close()

# create_partners.py

from sqlalchemy.orm import Session
from passlib.context import CryptContext
from database import SessionLocal
from models import User

# Setup password hasher
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Sample owner data
owners = [
    {"name": "Moraa Transport", "email": "moraa@example.com", "phone": "0702000001"},
    {"name": "Jabali Haulage", "email": "jabali@example.com", "phone": "0702000002"},
    {"name": "Safari Freight", "email": "safari@example.com", "phone": "0702000003"},
]


def create_owners():
    db: Session = SessionLocal()

    try:
        for owner in owners:
            existing = db.query(User).filter(
                User.phone == owner["phone"]).first()
            if existing:
                print(f"⚠️ Owner {owner['name']} already exists.")
                continue

            new_owner = User(
                name=owner["name"],
                email=owner["email"],
                phone=owner["phone"],
                password_hash=pwd_context.hash("ownerpass123"),
                role="owner"
            )
            db.add(new_owner)

        db.commit()
        print("✅ Owner accounts created successfully.")
    except Exception as e:
        db.rollback()
        print("❌ Error creating owner accounts:", str(e))
    finally:
        db.close()


if __name__ == "__main__":
    create_owners()

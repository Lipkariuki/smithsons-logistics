from sqlalchemy.orm import Session
from passlib.context import CryptContext
from database import SessionLocal
from models import User
from settings import required_env

# Setup password hasher
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def create_admin():
    password = required_env('BOOTSTRAP_ADMIN_PASSWORD')
    db: Session = SessionLocal()

    try:
        new_phone = "+254722760992"
        existing_admin = db.query(User).filter(User.phone == new_phone).first()
        if existing_admin:
            print(f"⚠️ Admin with phone {new_phone} already exists.")
            return

        new_admin = User(
            name="PHIL Admin",
            email="philqaris@gmail.com",
            phone=new_phone,
            password_hash=pwd_context.hash(password),
            role="admin"
        )
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)

        print("✅ New admin user created!")
        print(f"Phone: {new_admin.phone}")
        print(f"Email: {new_admin.email}")
    except Exception as e:
        db.rollback()
        print("Admin creation failed; verify configuration and account details")
    finally:
        db.close()

def create_specified_drivers():
    password = required_env('BOOTSTRAP_DRIVER_PASSWORD')
    db = SessionLocal()
    drivers = [
        {"name": "Stephen Maina", "phone": "+254711000201", "email": "stephen.maina@example.com"},
        {"name": "Robert Mwangi", "phone": "+254711000202", "email": "robert.mwangi@example.com"},
        {"name": "Kelvin Odur", "phone": "+254711000203", "email": "kelvin.odur@example.com"},
        {"name": "John Ochieng", "phone": "+254711000204", "email": "john.ochieng@example.com"},
        {"name": "Daniel Kairithia", "phone": "+254711000205", "email": "daniel.kairithia@example.com"},
    ]

    try:
        for d in drivers:
            exists = db.query(User).filter(User.phone == d["phone"]).first()
            if exists:
                print(f"⚠️ Driver already exists: {d['name']} ({d['phone']})")
                continue

            new_driver = User(
                name=d["name"],
                email=d["email"],
                phone=d["phone"],
                password_hash=pwd_context.hash(password),
                role="driver",
            )
            db.add(new_driver)

        db.commit()
        print("✅ Specified drivers created (where not existing).")
    except Exception as e:
        db.rollback()
        print("Driver creation failed; verify configuration and account details")
    finally:
        db.close()


if __name__ == "__main__":
    # Validate both explicit credentials before performing any account writes.
    required_env('BOOTSTRAP_ADMIN_PASSWORD')
    required_env('BOOTSTRAP_DRIVER_PASSWORD')
    create_admin()
    create_specified_drivers()

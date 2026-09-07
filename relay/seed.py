"""Create the first operator account. Idempotent: re-running updates the password."""
import argparse
import asyncio

from sqlalchemy import select

from app.core.security import hash_secret
from app.db.session import SessionLocal
from app.models import Operator


async def seed(email: str, password: str, full_name: str) -> None:
    async with SessionLocal() as db:
        operator = await db.scalar(select(Operator).where(Operator.email == email.lower()))
        if operator is None:
            operator = Operator(
                email=email.lower(),
                full_name=full_name,
                password_hash=hash_secret(password),
                role="admin",
            )
            db.add(operator)
            action = "created"
        else:
            operator.password_hash = hash_secret(password)
            operator.full_name = full_name or operator.full_name
            operator.is_active = True
            action = "updated"
        await db.commit()
        print(f"operator {action}: {email.lower()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="admin@example.com")
    parser.add_argument("--password", default="ChangeMe123!")
    parser.add_argument("--name", default="Platform Admin")
    args = parser.parse_args()
    asyncio.run(seed(args.email, args.password, args.name))

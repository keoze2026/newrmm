from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, current_operator
from app.core.config import settings
from app.core.security import create_access_token, verify_secret
from app.db.session import get_db
from app.models import Operator
from app.schemas.auth import LoginRequest, OperatorOut, TokenResponse
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    operator = await db.scalar(select(Operator).where(Operator.email == payload.email.lower()))
    ip = client_ip(request)

    if operator is None or not operator.is_active or not verify_secret(payload.password, operator.password_hash):
        await audit.record(
            db,
            action=audit.LOGIN_FAILED,
            actor_type="anonymous",
            actor_label=payload.email,
            ip=ip,
            detail={"reason": "invalid_credentials"},
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    operator.last_login_at = datetime.now(timezone.utc)
    await audit.record(
        db,
        action=audit.LOGIN_SUCCESS,
        actor_id=operator.id,
        actor_label=operator.email,
        target_type="operator",
        target_id=str(operator.id),
        ip=ip,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_access_token(str(operator.id), {"email": operator.email, "role": operator.role}),
        expires_in=settings.access_token_minutes * 60,
    )


@router.get("/me", response_model=OperatorOut)
async def me(operator: Operator = Depends(current_operator)) -> Operator:
    return operator

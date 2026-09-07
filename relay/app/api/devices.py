from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, current_operator
from app.core.codes import generate_device_secret
from app.core.security import hash_secret
from app.db.session import get_db
from app.models import Device, Operator
from app.schemas.device import DeviceCreate, DeviceEnrolled, DeviceOut
from app.services import audit

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("", response_model=DeviceEnrolled, status_code=status.HTTP_201_CREATED)
async def enroll_device(
    payload: DeviceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> DeviceEnrolled:
    secret = generate_device_secret()
    device = Device(name=payload.name, os=payload.os, secret_hash=hash_secret(secret))
    db.add(device)
    await db.flush()

    await audit.record(
        db,
        action=audit.DEVICE_ENROLLED,
        actor_id=operator.id,
        actor_label=operator.email,
        target_type="device",
        target_id=str(device.id),
        ip=client_ip(request),
        detail={"name": device.name, "os": device.os},
    )
    await db.commit()
    await db.refresh(device)

    return DeviceEnrolled(
        **DeviceOut.model_validate(device).model_dump(),
        enrollment_secret=secret,
    )


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    operator: Operator = Depends(current_operator),
) -> list[Device]:
    stmt = select(Device).order_by(Device.enrolled_at.desc())
    return list((await db.scalars(stmt)).all())

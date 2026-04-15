# app/routes/access_codes.py
"""
Access code management endpoints.
Admin: generate, list, revoke codes.
Users: redeem a code to activate their account.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user, get_admin_user
from app.models.api import AccessCodeCreate, AccessCodeRedeem
from app.services import access_code_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/access-codes", tags=["access-codes"])


@router.post("")
async def create_code(
    body: AccessCodeCreate,
    user: dict = Depends(get_admin_user),
):
    """Generate a new access code (admin only)."""
    code = await access_code_service.generate_code(
        label=body.label,
        max_uses=body.max_uses,
        created_by=str(user["_id"]),
    )
    return {
        "id": str(code["_id"]),
        "code": code["code"],
        "label": code.get("label", ""),
        "max_uses": code.get("max_uses", 1),
        "used_count": 0,
    }


@router.get("")
async def list_codes(
    user: dict = Depends(get_admin_user),
):
    """List all access codes (admin only)."""
    return await access_code_service.list_codes()


@router.delete("/{code_id}")
async def revoke_code(
    code_id: str,
    user: dict = Depends(get_admin_user),
):
    """Revoke an access code (admin only)."""
    revoked = await access_code_service.revoke_code(code_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Zugangscode nicht gefunden.")
    return {"status": "revoked"}


@router.post("/redeem")
async def redeem_code(
    body: AccessCodeRedeem,
    user: dict = Depends(get_current_user),
):
    """Redeem an access code to activate the account."""
    if user.get("activated"):
        return {"status": "already_activated"}

    try:
        await access_code_service.redeem_code(body.code, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "activated"}

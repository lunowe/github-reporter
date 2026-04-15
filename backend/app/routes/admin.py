# app/routes/admin.py
"""
Admin-only endpoints — user listing, etc.
"""

from fastapi import APIRouter, Depends

from app.auth import get_admin_user
from app.services.user_service import list_all_users

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    user: dict = Depends(get_admin_user),
):
    """List all registered users (admin only)."""
    return await list_all_users()

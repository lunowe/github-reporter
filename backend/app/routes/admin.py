# app/routes/admin.py
"""
Admin-only endpoints — user listing, repo management, etc.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_admin_user
from app.models.api import UserReposUpdate
from app.services.user_service import list_all_users, update_allowed_repos

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    user: dict = Depends(get_admin_user),
):
    """List all registered users (admin only)."""
    return await list_all_users()


@router.put("/users/{user_id}/repos")
async def update_user_repos(
    user_id: str,
    body: UserReposUpdate,
    user: dict = Depends(get_admin_user),
):
    """Update the allowed repositories for a viewer user (admin only)."""
    updated = await update_allowed_repos(user_id, body.allowed_repo_ids)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Benutzer nicht gefunden oder kein Viewer-Konto.",
        )
    return {"status": "updated", "allowed_repo_ids": updated.get("allowed_repo_ids", [])}

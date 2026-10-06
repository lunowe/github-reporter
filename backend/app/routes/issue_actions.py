"""
Issue drafts proposed by the chat agent.

GET  /api/issue-actions/{action_id}          fetch a draft (owner only)
POST /api/issue-actions/{action_id}/apply    perform it on GitHub (optional title/body edits)
POST /api/issue-actions/{action_id}/reject   discard it
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_activated_user
from app.services import issue_actions
from app.services.issue_actions import (
    IssueActionConflict,
    IssueActionForbidden,
    IssueActionInvalid,
    IssueActionNotFound,
)

router = APIRouter(prefix="/api/issue-actions", tags=["issue-actions"])


class ApplyRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None


def _http_error(e: Exception) -> HTTPException:
    if isinstance(e, IssueActionNotFound):
        return HTTPException(status_code=404, detail="Entwurf nicht gefunden.")
    if isinstance(e, IssueActionForbidden):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, IssueActionInvalid):
        return HTTPException(status_code=422, detail=str(e))
    return HTTPException(status_code=409, detail=str(e))


@router.get("/{action_id}")
async def get_issue_action(action_id: str, user: dict = Depends(get_activated_user)):
    try:
        return await issue_actions.get_action(action_id, user)
    except IssueActionNotFound as e:
        raise _http_error(e)


@router.post("/{action_id}/apply")
async def apply_issue_action(
    action_id: str,
    body: Optional[ApplyRequest] = None,
    user: dict = Depends(get_activated_user),
):
    body = body or ApplyRequest()
    try:
        return await issue_actions.apply(action_id, user, title=body.title, body=body.body)
    except (IssueActionNotFound, IssueActionForbidden, IssueActionConflict, IssueActionInvalid) as e:
        raise _http_error(e)


@router.post("/{action_id}/reject")
async def reject_issue_action(action_id: str, user: dict = Depends(get_activated_user)):
    try:
        return await issue_actions.reject(action_id, user)
    except (IssueActionNotFound, IssueActionConflict) as e:
        raise _http_error(e)

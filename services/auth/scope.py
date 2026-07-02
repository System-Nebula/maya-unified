"""Resolve which operator's workspace an API request may access."""

from __future__ import annotations

from fastapi import HTTPException, Request


def scoped_operator_id(request: Request, operator_id: str = "") -> str:
    """Return the operator whose data the request may touch.

    Non-admins are always scoped to themselves. Admins may pass ``operator_id``
    to act on another account.
    """
    op = getattr(request.state, "operator", None)
    if op is None:
        return ""
    target = (operator_id or "").strip()
    self_id = str(op.id)
    if target and op.role == "admin":
        return target
    if target and target != self_id:
        raise HTTPException(status_code=403, detail="cannot access another operator's data")
    return self_id

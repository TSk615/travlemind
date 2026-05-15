from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class XhsBindingStatusResponse(BaseModel):
    bind_id: str
    status: str
    verification_url: str | None = None
    verification_code: str | None = None
    qr_image_data_url: str | None = None
    expires_at: datetime | None = None
    completed_at: datetime | None = None
    message: str | None = None


class XhsAccountStatusResponse(BaseModel):
    xhs_bound: bool
    xhs_binding_required: bool
    xhs_session_expired: bool
    xhs_message: str | None = None
    xhs_display_name: str | None = None
    xhs_last_bound_at: datetime | None = None
    xhs_last_available_at: datetime | None = None
    active_binding: XhsBindingStatusResponse | None = None

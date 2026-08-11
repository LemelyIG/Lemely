"""Projection from the device registry's rows onto the wire DTOs (G-10, G-11).

One function, shared by the login challenge in ``routers/auth.py`` and the device
list in ``routers/me.py``, so the two surfaces cannot describe the same device
differently — the whole point of D5.12 is that a user confirms against exactly
what they are later managing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from lemely.web.schemas_devices import DeviceDTO

if TYPE_CHECKING:
    import uuid

    from lemely.db.device_repo import DeviceRow


def to_device_dto(
    row: DeviceRow, *, current_session_id: uuid.UUID | str | None = None
) -> DeviceDTO:
    """Project one :class:`~lemely.db.device_repo.DeviceRow` onto the wire DTO.

    ``current_session_id`` is the caller's own ``session_id`` claim when it has
    one; a login challenge passes ``None`` because the caller holds no session
    yet, and every device there is correctly marked not-current.
    """
    return DeviceDTO(
        deviceId=str(row.device_id),
        label=row.device_label,
        userAgent=row.user_agent,
        lastActiveAt=row.last_seen_at.isoformat(),
        isCurrent=current_session_id is not None and str(row.device_id) == str(current_session_id),
    )


__all__ = ["to_device_dto"]

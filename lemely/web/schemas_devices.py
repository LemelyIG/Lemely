"""API DTOs for the device/session surfaces (G-10, G-11).

Two readers share one shape: the **409 challenge** a login answers when it would
consume a fourth slot (D5.12), and the **device list** an authenticated user
manages under ``/api/me/devices``. They are the same query in
:class:`~lemely.db.device_repo.DeviceRegistry`, so they are the same DTO here —
a user must not be shown one set of devices when deciding and a different set
when acting.

**No location field exists on these DTOs, deliberately.** UI spec G-10 asks for a
rough location; this build stores no IP address and has no geo-IP source, so a
location could only be invented, which UI spec §1.4 forbids — and it is precisely
the field a user would base a "sign this one out" decision on (D5.12 §5).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base DTO: forbids extra fields and serialises via camelCase aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DeviceDTO(ApiModel):
    """One signed-in device.

    ``userAgent`` is the raw header as captured at login and may be ``None`` for a
    session registered without one; the client renders a short form from it rather
    than the server guessing a product name it cannot verify. ``isCurrent`` is
    ``True`` only for the device making the request, and is always ``False`` in a
    login challenge — at that point the caller holds no session at all.
    """

    deviceId: str
    label: str | None = None
    userAgent: str | None = None
    lastActiveAt: str
    isCurrent: bool = False


class DeviceListDTO(ApiModel):
    """The caller's signed-in devices, most-recently-active first."""

    devices: list[DeviceDTO]
    maxDevices: int


class DeviceRevokedDTO(ApiModel):
    """Outcome of signing a device out.

    ``removed`` is ``False`` when the device was already revoked, never existed,
    or belongs to somebody else — all three answer the same way, so the route
    cannot be used to test whether a device id exists on another account.
    ``wasCurrent`` tells the client its own token has just been invalidated, so it
    can sign out locally instead of discovering it on the next 401.
    """

    removed: bool
    wasCurrent: bool = False


class DeviceLimitChallengeDTO(ApiModel):
    """The 409 body for a login that would evict (D5.12).

    Carries the account's live devices and the id of the one a confirmed retry
    would sign out, so the UI states the consequence rather than re-deriving the
    eviction order from ``lastActiveAt`` and risking disagreeing with the server.
    """

    reason: str = "device_limit_reached"
    maxDevices: int
    devices: list[DeviceDTO]
    oldestDeviceId: str


__all__ = [
    "ApiModel",
    "DeviceDTO",
    "DeviceLimitChallengeDTO",
    "DeviceListDTO",
    "DeviceRevokedDTO",
]

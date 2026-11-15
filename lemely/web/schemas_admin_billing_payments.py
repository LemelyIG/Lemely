"""Request DTOs for the admin payments money actions (``/api/admin/billing/payments``, spec §8).

camelCase on the wire, ``extra="forbid"`` (``ApiModel``). The payment and refund response DTOs
live in ``schemas_admin_billing`` because the customer view and the problem queue emit them too
(DV-2, DV-21).
"""

from __future__ import annotations

from lemely.web.schemas_admin import ApiModel
from lemely.web.schemas_admin_billing import (  # noqa: TC001 - pydantic field types
    PositiveMoney,
    Reason,
)


class AdminRefundRequestDTO(ApiModel):  # type: ignore[explicit-any]  # pydantic plugin
    """``amountMinor`` ``None`` refunds everything not yet refunded."""

    amountMinor: PositiveMoney | None = None
    reason: Reason

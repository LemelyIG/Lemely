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


class AdminRefundRequestDTO(ApiModel):
    """``amountMinor`` ``None`` refunds everything not yet refunded.

    ``reverseChange`` also undoes what the payment bought (UD-4); the default is money only.
    """

    amountMinor: PositiveMoney | None = None
    reverseChange: bool = False
    reason: Reason

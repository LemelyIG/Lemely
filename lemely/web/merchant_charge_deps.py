"""The collaborators the merchant-charge routes need, as one overridable bundle (Phase 06 T9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lemely.db.merchant_charge_repo import MerchantChargeService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings


@dataclass(frozen=True, slots=True)
class MerchantChargeDeps:
    """Session factory, Paymob client and settings. Tests override the provider with a fake."""

    sessionmaker: sessionmaker[Session]
    client: PaymobClient
    settings: PaymobSettings

    def service(self, session: Session) -> MerchantChargeService:
        """A service over ``session``; the caller decides where the transaction ends."""
        return MerchantChargeService(session, self.client, self.settings)


__all__ = ["MerchantChargeDeps"]

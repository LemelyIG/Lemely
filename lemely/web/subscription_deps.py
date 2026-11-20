"""The collaborators every subscription route and job needs, as one overridable bundle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from lemely.db.subscription_repo import SubscriptionService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from lemely.io.paymob.client import PaymobClient
    from lemely.runtime.config import PaymobSettings


@dataclass(frozen=True, slots=True)
class SubscriptionDeps:
    """Session factory, Paymob client and settings. Tests override the provider with a fake."""

    sessionmaker: sessionmaker[Session]
    client: PaymobClient
    settings: PaymobSettings

    def service(self, session: Session) -> SubscriptionService:
        """A service over ``session``; the caller decides where the transaction ends."""
        return SubscriptionService(session, self.client, self.settings)


__all__ = ["SubscriptionDeps"]

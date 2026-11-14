"""Dependencies for the admin billing routers; tests override each one.

Built per request: a service holds only the process sessionmaker and the Paymob
client, so construction is free.
"""

from __future__ import annotations

from lemely.db.admin_billing_repo import AdminCatalogueService
from lemely.db.session import get_sessionmaker
from lemely.web.deps import get_settings
from lemely.web.deps_billing import get_paymob_client


def get_admin_catalogue_service() -> AdminCatalogueService:
    settings = get_settings()
    return AdminCatalogueService(get_sessionmaker(settings), get_paymob_client(), settings.paymob)


__all__ = ["get_admin_catalogue_service"]

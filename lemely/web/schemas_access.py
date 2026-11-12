"""``GET /api/access/config`` wire contract."""

from __future__ import annotations

from lemely.web.schemas import ApiModel


class AccessConfigDTO(ApiModel):
    """Whether account creation and sign-in are limited to an allow-list right now.

    A boolean only: the allowed domains are never part of the response.
    """

    restricted: bool

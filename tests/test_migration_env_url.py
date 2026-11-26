"""``lemely/db/migrations/env.py`` must accept a percent-encoded database password.

``alembic.ini`` is read through ``ConfigParser``, which interpolates ``%``: handing it the raw
URL ``postgresql+psycopg://u:p%40ss@host/db`` fails with ``ValueError: invalid interpolation
syntax`` before alembic connects to anything. The env script escapes ``%`` as ``%%`` and alembic
un-escapes it on read.

The URL below points at a closed port on loopback, so the only thing the run can do is fail to
connect: the test touches no database.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def test_a_percent_encoded_password_reaches_the_connect_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "LEMELY_DATABASE__URL",
        "postgresql+psycopg://user:p%40ss%25word@127.0.0.1:1/lemely_test_none",
    )

    with pytest.raises(sa.exc.OperationalError, match="port 1 failed"):
        command.current(Config("alembic.ini"))

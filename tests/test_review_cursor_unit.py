import base64
import uuid

import pytest
from fastapi import HTTPException

from lemely.web.routers.review import _decode_cursor


@pytest.mark.parametrize("sort", ["oldest", "most_marks_lost"])
def test_cursor_rejects_naive_datetimes(sort):
    item_id = uuid.uuid4()
    raw = f"2026-01-01T00:00:00|{item_id}"
    if sort != "oldest":
        raw = f"v2|{sort}|0|0.0|{raw}"
    malformed = base64.urlsafe_b64encode(raw.encode()).decode()
    with pytest.raises(HTTPException) as error:
        _decode_cursor(malformed, sort)
    assert error.value.status_code == 422

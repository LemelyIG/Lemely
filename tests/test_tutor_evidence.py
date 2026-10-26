"""Tutor evidence routes T6 (upload) and T7 (delete) (SPEC §b.2 "Tutor", §a.2, SC-7, SC-22, O20).

Cross-cutting obligations of PLAN "Global constraints" for these two routes:
(a) ``no-store`` on each success path, (b) SC-7 for the one free-text field
(``description``), (d) ``tutor_suspended`` / ``tutor_closed`` on both (both are
writes), and (f) ``no_tutor_profile`` 404 on both. Neither route is **V**.
The repository's own transaction re-checks the limit and the listing state, so
the guard is the fast answer, not the only one.
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from io import BytesIO
from typing import TYPE_CHECKING

import pymupdf
import pytest
import sqlalchemy as sa
import structlog.testing
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

from lemely.db.models.enums import Role
from lemely.db.models.tutoring import TutorEvidenceFile
from lemely.db.tutor_evidence_repo import (
    MAX_EVIDENCE_FILES,
    EvidenceLimitError,
    TutorEvidenceRepository,
)
from lemely.db.tutor_profile_repo import TutorClosedError, TutorSuspendedError
from lemely.io.evidence_files import EVIDENCE_PREPARE_TARGET, MAX_EVIDENCE_BYTES
from lemely.runtime import sandbox
from lemely.runtime.config import SandboxSettings
from lemely.runtime.errors import ExternalServiceError
from lemely.web.routers.tutor_evidence import get_tutor_evidence_repo
from tests.sandbox_fixtures import in_process_sandbox, sandboxed  # noqa: F401
from tests.storage_fakes import FakeStorageBackend
from tests.test_evidence_files import (
    pdf_with_open_action_and_attachments,
    pdf_with_scripted_widget,
)
from tests.test_web_admin_tutoring import PDF, admin_tutoring_client, evidence_bucket
from tests.tutoring_db import act_as, add_tutor, add_user, emptied_after, tutoring_database

if TYPE_CHECKING:
    from collections.abc import Iterator

    from httpx import Response
    from sqlalchemy.orm import Session, sessionmaker

NO_STORE = "private, no-store"
URL = "/api/tutor/profile/evidence"


@pytest.fixture(scope="module")
def tutoring_db() -> Iterator[sessionmaker[Session]]:
    with tutoring_database() as factory:
        yield factory


@pytest.fixture
def sm(tutoring_db: sessionmaker[Session]) -> Iterator[sessionmaker[Session]]:
    yield from emptied_after(tutoring_db)


@pytest.fixture
def storage() -> FakeStorageBackend:
    return FakeStorageBackend()


@pytest.fixture
def client(sm: sessionmaker[Session], storage: FakeStorageBackend) -> Iterator[TestClient]:
    test_client = admin_tutoring_client(sm, storage)
    yield test_client
    test_client.app.dependency_overrides.clear()  # type: ignore[attr-defined]


def _png_with_text() -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Sara Mansour")
    buf = BytesIO()
    Image.new("RGB", (20, 20), (10, 120, 200)).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _rows(sm: sessionmaker[Session]) -> list[TutorEvidenceFile]:
    with sm() as session:
        return list(session.scalars(sa.select(TutorEvidenceFile)))


def _pages(data: bytes) -> int:
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        return int(doc.page_count)
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _objects(storage: FakeStorageBackend) -> dict[tuple[str, str], bytes]:
    return dict(storage._objects)


def _upload(
    client: TestClient,
    data: bytes = PDF,
    *,
    filename: str = "degree.pdf",
    declared: str = "application/pdf",
    description: str | None = None,
) -> Response:
    form = {"description": description} if description is not None else {}
    return client.post(URL, files={"file": (filename, data, declared)}, data=form)


def _tutor(client: TestClient, sm: sessionmaker[Session], state: str = "listed") -> uuid.UUID:
    tutor = add_tutor(sm, state=state)
    act_as(client, tutor.user_id, Role.teacher)
    return tutor.profile_id


# ---------------------------------------------------------------------------
# T6 upload
# ---------------------------------------------------------------------------


def test_t6_stores_a_pdf_under_a_server_path_and_returns_201(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    profile_id = _tutor(client, sm)
    uploaded = pdf_with_open_action_and_attachments()

    response = _upload(client, uploaded, description="  BSc certificate  ")

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == NO_STORE
    body = response.json()
    assert set(body) == {
        "evidenceId",
        "filename",
        "contentType",
        "sizeBytes",
        "description",
        "uploadedAt",
    }
    assert body["filename"] == "degree.pdf"
    assert body["contentType"] == "application/pdf"
    assert body["description"] == "BSc certificate"
    [row] = _rows(sm)
    assert str(row.id) == body["evidenceId"]
    assert row.storage_path == f"tutor-evidence/{profile_id}/{row.id}.pdf"
    [(key, stored)] = _objects(storage).items()
    assert key == (evidence_bucket(), row.storage_path)
    # R1: what is stored is MuPDF's pages-only rewrite, not the uploaded bytes.
    assert b"/OpenAction" in uploaded
    assert b"/EmbeddedFiles" in uploaded
    assert stored.startswith(b"%PDF-")
    for gone in (b"/OpenAction", b"JavaScript", b"EmbeddedFile"):
        assert gone not in stored, gone
    assert _pages(stored) == 1
    assert body["sizeBytes"] == row.size_bytes == len(stored)


def test_t6_sniffed_type_and_reencode_decide_what_is_stored(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    _tutor(client, sm)
    png = _png_with_text()

    response = _upload(client, png, filename="scan.pdf", declared="application/pdf")

    assert response.status_code == 201
    body = response.json()
    assert body["contentType"] == "image/png"
    assert body["filename"] == "scan.png"
    [row] = _rows(sm)
    assert row.content_type == "image/png"
    assert row.storage_path.endswith(".png")
    stored = _objects(storage)[(evidence_bucket(), row.storage_path)]
    assert b"Sara Mansour" in png
    assert b"Sara Mansour" not in stored
    assert row.size_bytes == len(stored) == body["sizeBytes"]


def test_t6_refusals_413_and_415_store_nothing(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    _tutor(client, sm)

    too_big = _upload(client, PDF + b"\x00" * (MAX_EVIDENCE_BYTES + 1 - len(PDF)))
    gif = _upload(client, b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", filename="a.gif")
    polyglot = _upload(client, b"%PDF-1.7\n%<script>alert(1)</script>\n" + PDF[9:])
    junk = _upload(client, b"%PDF-1.7\n" + b"not a pdf " * 200)
    scripted = _upload(client, pdf_with_scripted_widget())

    assert too_big.status_code == 413
    assert too_big.json()["detail"]["code"] == "evidence_too_large"
    assert too_big.headers["cache-control"] == NO_STORE
    for refused in (gif, polyglot, junk, scripted):
        assert refused.status_code == 415
        assert refused.json()["detail"]["code"] == "unsupported_evidence_type"
    assert _rows(sm) == []
    assert _objects(storage) == {}


@pytest.mark.parametrize(
    ("description", "code"),
    [
        ("Call me on 01012345678", "contact_details_not_allowed"),
        ("sara@example.com", "contact_details_not_allowed"),
        ("x" * 201, "invalid_description"),
    ],
)
def test_t6_description_validated_422(
    client: TestClient,
    sm: sessionmaker[Session],
    storage: FakeStorageBackend,
    description: str,
    code: str,
) -> None:
    """SC-7 / SPEC §a.2: ``description`` passes contact-pattern validation, <= 200."""
    _tutor(client, sm)
    response = _upload(client, description=description)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert _rows(sm) == []
    assert _objects(storage) == {}


def test_evidence_limit_409(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    _tutor(client, sm)
    assert MAX_EVIDENCE_FILES == 5
    for index in range(MAX_EVIDENCE_FILES):
        assert _upload(client, filename=f"{index}.pdf").status_code == 201

    sixth = _upload(client, filename="6.pdf")

    assert sixth.status_code == 409
    assert sixth.json()["detail"]["code"] == "evidence_limit"
    assert sixth.headers["cache-control"] == NO_STORE
    assert len(_rows(sm)) == MAX_EVIDENCE_FILES
    assert len(_objects(storage)) == MAX_EVIDENCE_FILES


def test_evidence_limit_rechecked_in_the_write_transaction(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    """A race past the route's pre-check still meets the limit, and the object is removed."""
    profile_id = _tutor(client, sm)
    repo = TutorEvidenceRepository(sm)
    for index in range(MAX_EVIDENCE_FILES):
        repo.add(
            profile_id,
            evidence_id=uuid.uuid4(),
            storage_path=f"tutor-evidence/{profile_id}/{index}.pdf",
            filename=f"{index}.pdf",
            content_type="application/pdf",
            size_bytes=10,
            description=None,
        )
    with pytest.raises(EvidenceLimitError):
        repo.add(
            profile_id,
            evidence_id=uuid.uuid4(),
            storage_path=f"tutor-evidence/{profile_id}/x.pdf",
            filename="x.pdf",
            content_type="application/pdf",
            size_bytes=10,
            description=None,
        )

    class _BlindCount(TutorEvidenceRepository):
        def count(self, profile_id: uuid.UUID) -> int:  # the pre-check loses the race
            return 0

    client.app.dependency_overrides[get_tutor_evidence_repo] = lambda: _BlindCount(sm)  # type: ignore[attr-defined]
    raced = _upload(client)

    assert raced.status_code == 409
    assert raced.json()["detail"]["code"] == "evidence_limit"
    assert len(_rows(sm)) == MAX_EVIDENCE_FILES
    assert _objects(storage) == {}  # the uploaded object was deleted again


def test_evidence_limit_holds_under_concurrent_adds_at_four(sm: sessionmaker[Session]) -> None:
    """T10 review R5: two adds race at four files; the profile row lock lets exactly one in.

    Each racer is held just before its commit until the other arrives (or 2 s pass). With
    the ``FOR UPDATE`` lock the second racer cannot even count until the first commits, so
    it never arrives and then sees five; without it both count four and both commit.
    """
    tutor = add_tutor(sm, state="listed")
    repo = TutorEvidenceRepository(sm)

    def add() -> None:
        evidence_id = uuid.uuid4()
        repo.add(
            tutor.profile_id,
            evidence_id=evidence_id,
            storage_path=f"tutor-evidence/{tutor.profile_id}/{evidence_id}.pdf",
            filename="race.pdf",
            content_type="application/pdf",
            size_bytes=10,
            description=None,
        )

    for _ in range(MAX_EVIDENCE_FILES - 1):
        add()
    start = threading.Barrier(2, timeout=10)
    before_commit = threading.Barrier(2, timeout=2)
    outcomes: dict[str, str] = {}

    def hold(_session: Session) -> None:
        if threading.current_thread().name.startswith("evidence-race"):
            # Broken after 2 s when the other racer is blocked on the row lock: commit alone.
            with contextlib.suppress(threading.BrokenBarrierError):
                before_commit.wait()

    def race() -> None:
        start.wait()
        try:
            add()
            outcomes[threading.current_thread().name] = "added"
        except EvidenceLimitError as exc:
            outcomes[threading.current_thread().name] = exc.code

    sa.event.listen(sm, "before_commit", hold)
    try:
        racers = [threading.Thread(target=race, name=f"evidence-race-{n}") for n in range(2)]
        for racer in racers:
            racer.start()
        for racer in racers:
            racer.join(timeout=30)
    finally:
        sa.event.remove(sm, "before_commit", hold)

    assert sorted(outcomes.values()) == ["added", "evidence_limit"]
    assert len(_rows(sm)) == MAX_EVIDENCE_FILES


@pytest.mark.usefixtures("sandboxed")
def test_t6_checks_each_file_in_the_extraction_worker_one_at_a_time(
    client: TestClient,
    sm: sessionmaker[Session],
    storage: FakeStorageBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T10 review R2: the decode and the PDF rewrite run in the memory-limited worker.

    Its lock admits one check at a time, so while another call holds it an upload
    waits out the upload-check timeout and is told to try again (503), storing nothing.
    """
    _tutor(client, sm)
    monkeypatch.setattr(
        sandbox,
        "sandbox_settings",
        lambda: SandboxSettings(enabled=True, upload_check_timeout_seconds=0.5),
    )

    with sandbox.EXTRACTION_WORKER._lock:
        busy = _upload(client, _png_with_text(), filename="a.png", declared="image/png")

    assert busy.status_code == 503
    assert busy.json()["detail"]["code"] == "evidence_check_unavailable"
    assert busy.headers["cache-control"] == NO_STORE
    assert sandbox.EXTRACTION_WORKER.last_outcome == "busy"
    assert _rows(sm) == []
    assert _objects(storage) == {}

    freed = _upload(client, _png_with_text(), filename="a.png", declared="image/png")
    assert freed.status_code == 201, freed.text
    assert sandbox.EXTRACTION_WORKER.last_outcome == "ok"
    assert sandbox.EXTRACTION_WORKER.pid() is not None


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (sandbox.SandboxUnavailable("down", "unavailable"), 503, "evidence_check_unavailable"),
        (sandbox.SandboxBusy(), 503, "evidence_check_unavailable"),
        (sandbox.SandboxMemory("out of memory", "memory"), 413, "evidence_too_large"),
        (sandbox.SandboxTimeout("too slow", "timeout"), 415, "unsupported_evidence_type"),
        (sandbox.SandboxCrash("gone", "crash"), 415, "unsupported_evidence_type"),
        (sandbox.SandboxError("ValueError()", "error"), 415, "unsupported_evidence_type"),
    ],
    ids=["unavailable", "busy", "memory", "timeout", "crash", "error"],
)
def test_t6_worker_failures_map_to_fixed_answers(
    client: TestClient,
    sm: sessionmaker[Session],
    storage: FakeStorageBackend,
    monkeypatch: pytest.MonkeyPatch,
    failure: sandbox.SandboxFailure,
    status: int,
    code: str,
) -> None:
    _tutor(client, sm)
    targets: list[str] = []

    def call(target: str, *args: object, **kwargs: object) -> object:
        targets.append(target)
        raise failure

    monkeypatch.setattr(sandbox.EXTRACTION_WORKER, "call", call)
    with structlog.testing.capture_logs() as logs:
        response = _upload(client)

    assert targets == [EVIDENCE_PREPARE_TARGET]
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert str(failure) not in response.text  # a worker's own text is for the logs only
    assert [
        entry["reason"] for entry in logs if entry["event"] == "tutor_evidence_check_failed"
    ] == [failure.reason]
    assert _rows(sm) == []
    assert _objects(storage) == {}


def test_t6_storage_failure_503_writes_no_row(
    client: TestClient, sm: sessionmaker[Session]
) -> None:
    _tutor(client, sm)

    class _Down(FakeStorageBackend):
        def upload(
            self, bucket: str, object_path: str, data: bytes, content_type: str | None
        ) -> None:
            raise ExternalServiceError("storage unreachable")

    from lemely.web.deps import get_storage_backend

    client.app.dependency_overrides[get_storage_backend] = _Down  # type: ignore[attr-defined]
    response = _upload(client)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "storage_unavailable"
    assert _rows(sm) == []


def test_t6_t7_404_no_tutor_profile(client: TestClient, sm: sessionmaker[Session]) -> None:
    """(f) ADR-T01 action 3: a teacher without a profile gets 404 ``no_tutor_profile``."""
    teacher = add_user(sm, Role.teacher)
    act_as(client, teacher, Role.teacher)

    upload = _upload(client)
    delete = client.delete(f"{URL}/{uuid.uuid4()}")

    for response in (upload, delete):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "no_tutor_profile"
        assert response.headers["cache-control"] == NO_STORE


@pytest.mark.parametrize(
    ("state", "code"), [("suspended", "tutor_suspended"), ("closed", "tutor_closed")]
)
def test_t6_t7_409_for_a_suspended_or_closed_profile(
    client: TestClient,
    sm: sessionmaker[Session],
    storage: FakeStorageBackend,
    state: str,
    code: str,
) -> None:
    """(d) CB-7: both are tutor writes."""
    profile_id = _tutor(client, sm, state=state)
    with sm.begin() as session:
        session.add(
            TutorEvidenceFile(
                id=(evidence_id := uuid.uuid4()),
                tutor_profile_id=profile_id,
                storage_path=f"tutor-evidence/{profile_id}/{evidence_id}.pdf",
                original_filename="a.pdf",
                content_type="application/pdf",
                size_bytes=10,
            )
        )

    upload = _upload(client)
    delete = client.delete(f"{URL}/{evidence_id}")

    for response in (upload, delete):
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == code
        assert response.headers["cache-control"] == NO_STORE
    assert len(_rows(sm)) == 1
    assert _objects(storage) == {}


@pytest.mark.parametrize(
    ("state", "error"), [("suspended", TutorSuspendedError), ("closed", TutorClosedError)]
)
def test_repository_rechecks_the_listing_state_inside_the_write(
    sm: sessionmaker[Session], state: str, error: type[Exception]
) -> None:
    """A suspension that commits after the route's guard still wins (SPEC §a.4b)."""
    tutor = add_tutor(sm, state=state)
    repo = TutorEvidenceRepository(sm)
    with pytest.raises(error):
        repo.add(
            tutor.profile_id,
            evidence_id=uuid.uuid4(),
            storage_path=f"tutor-evidence/{tutor.profile_id}/x.pdf",
            filename="x.pdf",
            content_type="application/pdf",
            size_bytes=10,
            description=None,
        )
    with pytest.raises(error):
        repo.delete(tutor.profile_id, uuid.uuid4())


# ---------------------------------------------------------------------------
# T7 delete
# ---------------------------------------------------------------------------


def test_t7_deletes_the_row_then_the_object_204(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    _tutor(client, sm)
    evidence_id = _upload(client).json()["evidenceId"]
    assert len(_objects(storage)) == 1

    response = client.delete(f"{URL}/{evidence_id}")

    assert response.status_code == 204
    assert response.headers["cache-control"] == NO_STORE
    assert response.content == b""
    assert _rows(sm) == []
    assert _objects(storage) == {}
    again = client.delete(f"{URL}/{evidence_id}")
    assert again.status_code == 404
    assert again.json()["detail"]["code"] == "evidence_not_found"


def test_delete_after_commit_logs_orphan(
    client: TestClient, sm: sessionmaker[Session], storage: FakeStorageBackend
) -> None:
    """The object goes after the row's delete has committed; a failure is logged with its path."""
    _tutor(client, sm)
    evidence_id = uuid.UUID(_upload(client).json()["evidenceId"])
    [row] = _rows(sm)
    path = row.storage_path
    seen_rows_at_delete: list[int] = []

    class _DeleteFails(FakeStorageBackend):
        def delete(self, bucket: str, object_path: str) -> None:
            # A fresh session sees only committed data: the row must already be gone.
            seen_rows_at_delete.append(len(_rows(sm)))
            raise ExternalServiceError("storage unreachable")

    failing = _DeleteFails()
    from lemely.web.deps import get_storage_backend

    client.app.dependency_overrides[get_storage_backend] = lambda: failing  # type: ignore[attr-defined]
    with structlog.testing.capture_logs() as logs:
        response = client.delete(f"{URL}/{evidence_id}")

    assert response.status_code == 204
    assert seen_rows_at_delete == [0]
    orphans = [entry for entry in logs if entry["event"] == "tutor_evidence_orphan"]
    assert len(orphans) == 1
    assert orphans[0]["storage_path"] == path
    assert orphans[0]["bucket"] == evidence_bucket()
    assert orphans[0]["log_level"] == "error"
    assert _rows(sm) == []

"""API contract pins for the tutoring DTOs (PLAN T04; SPEC §b.3, §a.5, §c.3, ADR-T03).

Two modules hold the contract: ``lemely.web.schemas_tutoring`` (every class in
SPEC §b.3's code block) and ``lemely.web.schemas_tutoring_admin`` (the admin
DTOs §b.3 names without fields; their field sets are derived from §b.2 A1-A12
and §d X-04..X-07 in the T04 hand-off).

The expected side of every check is read from ``docs/tutoring/SPEC.md`` itself
(the §b.3 code block, the §b.2 route tables, the §a.1 enum table, the §c.3 O31
row) wherever SPEC states it, so a test never compares the modules with a
literal written from the same source as the modules (PLAN §0.8). The two
literals below that SPEC cannot supply are labelled where they are defined:
the row-5b public allowlist (SPEC §a.5 states it as columns, not wire fields)
and the admin DTOs added by the derivation.

Every scan asserts how many classes it looked at, so a discovery bug can never
turn a scan into a vacuous pass.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import inspect
import re
import types
import typing
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from lemely.db.tutor_review_repo import text_revision
from lemely.web import schemas_tutoring, schemas_tutoring_admin
from lemely.web.schemas import ApiModel
from lemely.web.schemas_analytics import StudentDetailDTO

SPEC_PATH = Path(__file__).resolve().parents[1] / "docs" / "tutoring" / "SPEC.md"

# Admin DTOs the T04 derivation adds beyond SPEC §b.3's admin list. Each one is
# justified line by line in BUILD/tutoring/handoffs/T04.md.
#   AdminBookingSummaryDTO: the type of ReportDetailDTO.bookingSummary (§b.2
#   A10 "the booking summary"; §b.3 names the field, not its type).
ADMIN_DERIVED_DTO_NAMES: frozenset[str] = frozenset({"AdminBookingSummaryDTO"})

# SPEC §a.5 "Public on the open web: public_first_name, public_last_initial,
# headline, modes, area_code (city), subjects, rating_avg/rating_count. Nothing
# else, ever." (decision-log row 5b; row 17 adds `indexable` to P2 only),
# written as the wire fields of every DTO a PUBLIC route can serialise (P14).
ROW_5B_CARD_FIELDS = frozenset(
    {"tutorId", "publicName", "headline", "subjects", "modes", "area", "rating"}
)
ROW_5B_PUBLIC_FIELDS: dict[str, frozenset[str]] = {
    "TutorCardDTO": ROW_5B_CARD_FIELDS,
    "PublicTutorCardDTO": ROW_5B_CARD_FIELDS | {"indexable"},
    "RatingDTO": frozenset({"state", "average", "count"}),
    "SubjectRefDTO": frozenset({"code", "name"}),
    "AreaRefDTO": frozenset({"code", "name"}),
    "AreaListDTO": frozenset({"items"}),
    "DirectoryFacetsDTO": frozenset({"subjects", "areas"}),
    "PublicDirectoryPageDTO": frozenset({"items", "nextCursor", "facets"}),
}

# SPEC §a.5 "Admin only: evidence files, approval notes, target_snapshot,
# account email on X-05": the field that carries each, and the one admin DTO
# allowed to carry it (O17 for evidence URLs, SC-23 for both logged reads).
ADMIN_ONLY_FIELD_OWNERS: dict[str, str] = {
    "accountEmail": "AdminTutorDetailDTO",
    "signedUrl": "AdminEvidenceDTO",
    "history": "AdminTutorDetailDTO",
    "snapshot": "ReportDetailDTO",
}

# SPEC §a.5: the meeting link goes to participants and linked parents only
# (O16), and a student's name to their tutor, their parents and themselves
# only. Neither reaches a platform admin.
NEVER_ON_ADMIN_DTOS = frozenset({"meetingLink", "displayName", "studentId"})
# SPEC §a.5 (fix lane F7-25 #3): an in-person session's place reaches a
# platform admin on a reported booking's summary only, and on no other admin
# DTO.
ADMIN_LOCATION_OWNERS = frozenset({"AdminBookingSummaryDTO"})

# SC-9: the only non-admin DTO fields whose type can hold the value "parent".
# BookingDTO reaches tutors, so its builder maps each to "student" for a tutor
# viewer (lead decision on the T04 review, R4). No builder exists yet.
PARENT_VALUED_BOOKING_FIELDS = frozenset(
    {("BookingDTO", "requestedBy"), ("BookingDTO", "cancelledBy"), ("BookingDTO", "completedBy")}
)

# The field-line shape web/tests/unit/tutoringTypesParity.test.ts reads when it
# parses these modules as text (its `fieldLine` regex). Kept in step by hand.
TS_PARITY_FIELD_LINE = re.compile(r"^ {4}(\w+): ")


# ── SPEC parsing ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SpecField:
    annotation: str  # whitespace removed, double quotes
    default: str | None  # the SPEC's default source text, None when it gives none


@dataclass(frozen=True)
class SpecClass:
    base: str
    fields: dict[str, SpecField]  # own fields only
    header_comment: str


@functools.cache
def _spec_text() -> str:
    return SPEC_PATH.read_text(encoding="utf-8")


def _section(start: str, end: str) -> str:
    text = _spec_text()
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


@functools.cache
def _b3_code() -> str:
    blocks = re.findall(r"```python\n(.*?)```", _section("### b.3 DTOs", "### b.4 "), re.DOTALL)
    assert len(blocks) == 1, f"SPEC §b.3 should hold one python block, found {len(blocks)}"
    return blocks[0]


def _norm(annotation: str) -> str:
    return re.sub(r"\s+", "", annotation).replace("'", '"')


def _depth(text: str) -> int:
    return text.count("[") - text.count("]")


_CLASS_LINE = re.compile(r"^class (\w+)\((\w+)\):(.*)$")
_FIELD_CHUNK = re.compile(r"(\w+)\s*:\s*(.+?)(?:\s*=\s*(.+))?")


@functools.cache
def _spec_b3_classes() -> dict[str, SpecClass]:
    """Every ``class …(…):`` in the §b.3 block with its own fields, in order."""
    bodies: dict[str, list[str]] = {}
    heads: dict[str, tuple[str, str]] = {}
    current: str | None = None
    for raw in _b3_code().splitlines():
        match = _CLASS_LINE.match(raw)
        if match:
            current = match.group(1)
            body, _, comment = match.group(3).partition("#")
            heads[current] = (match.group(2), comment.strip())
            bodies[current] = [body]
        elif not raw.startswith(" "):
            current = None  # an alias, a comment or a blank line ends a class
        elif current is not None:
            bodies[current].append(raw.partition("#")[0])
    classes: dict[str, SpecClass] = {}
    for name, lines in bodies.items():
        logical: list[str] = []
        for line in (text.strip() for text in lines):
            if not line:
                continue
            if logical and _depth(logical[-1]) > 0:
                logical[-1] += " " + line
            else:
                logical.append(line)
        fields: dict[str, SpecField] = {}
        for chunk in (piece.strip() for line in logical for piece in line.split(";")):
            if not chunk or chunk == "pass":
                continue
            field = _FIELD_CHUNK.fullmatch(chunk)
            assert field, f"unparsed SPEC field chunk in {name}: {chunk!r}"
            default = field.group(3).strip() if field.group(3) else None
            fields[field.group(1)] = SpecField(_norm(field.group(2)), default)
        base, comment = heads[name]
        classes[name] = SpecClass(base, fields, comment)
    return classes


@functools.cache
def _spec_b3_aliases() -> dict[str, tuple[str, ...]]:
    found = re.findall(r"^(\w+Lit) = Literal\[(.*?)\]", _b3_code(), re.MULTILINE | re.DOTALL)
    return {name: tuple(re.findall(r'"([^"]*)"', values)) for name, values in found}


@functools.cache
def _spec_admin_names() -> tuple[str, ...]:
    section = _section("### b.3 DTOs", "### b.4 ")
    start = section.index("Admin DTOs (`schemas_tutoring_admin.py`):")
    paragraph = section[start : section.index("**", start)]
    return tuple(dict.fromkeys(re.findall(r"`(\w+DTO)`", paragraph)))


def _spec_admin_note(name: str) -> str:
    """The parenthesised note §b.3's admin paragraph gives ``name``."""
    match = re.search(rf"`{name}` \(([^)]*)\)", _section("### b.3 DTOs", "### b.4 "))
    assert match, f"SPEC §b.3 gives {name} no field note"
    return match.group(1)


def _note_fields(note: str) -> frozenset[str]:
    """The backticked field names a note declares: those before its first colon."""
    fields = frozenset(re.findall(r"`(\w+)`", note.partition(":")[0]))
    assert fields, f"no backticked field names in {note!r}"
    return fields


@functools.cache
def _spec_admin_detail_extra_fields() -> frozenset[str]:
    """The fields §b.3 adds to ``AdminTutorDetailDTO`` on top of the own profile.

    Read from "`AdminTutorDetailDTO` (TutorOwnProfileDTO fields + `a`, `b`, …)";
    any change to that wording fails here rather than passing on a stale set.
    """
    match = re.search(
        r"`AdminTutorDetailDTO` \(TutorOwnProfileDTO fields \+ ([^)]*)\)",
        _section("### b.3 DTOs", "### b.4 "),
    )
    assert match, (
        "SPEC §b.3 no longer defines AdminTutorDetailDTO as 'TutorOwnProfileDTO fields + …'"
    )
    fields = frozenset(re.findall(r"`(\w+)`", match.group(1)))
    assert fields, f"no backticked field names in {match.group(1)!r}"
    return fields


@functools.cache
def _spec_b2_rows() -> dict[str, dict[str, str]]:
    """Every §b.2 route row keyed by its id (P1, SP6, T20, A12 …)."""
    rows: dict[str, dict[str, str]] = {}
    header: list[str] | None = None
    heading = ""
    for line in _section("### b.2 Routes", "### b.3 DTOs").splitlines():
        if line.startswith("#### "):
            heading, header = line[5:], None
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if cells[0] == "#":
            header = cells
        elif header is not None and re.fullmatch(r"[A-Z]+\d+", cells[0]):
            rows[cells[0]] = {**dict(zip(header, cells, strict=True)), "heading": heading}
    return rows


def _dto_names(cell: str) -> list[str]:
    return re.findall(r"\b([A-Z]\w*DTO)\b", cell)


def _b2_dtos_under(heading_prefix: str) -> set[str]:
    names: set[str] = set()
    for row in _spec_b2_rows().values():
        if row["heading"].startswith(heading_prefix):
            names.update(_dto_names(row["Request"]) + _dto_names(row["Response"]))
    return names


@functools.cache
def _spec_a1_enums() -> dict[str, tuple[str, ...]]:
    enums: dict[str, tuple[str, ...]] = {}
    for line in _section("### a.1 Enum types", "### a.2 Tables").splitlines():
        row = re.fullmatch(r"\| `(\w+)` \| (.+) \| `\w+` \|", line)
        if row:
            enums[row.group(1)] = tuple(re.findall(r"`(\w+)`", row.group(2)))
    return enums


def _spec_c3_row(rule: str) -> str:
    lines = [line for line in _spec_text().splitlines() if line.startswith(f"| {rule} |")]
    assert len(lines) == 1, f"SPEC §c.3 should have one {rule} row"
    return lines[0]


# ── Module introspection ──────────────────────────────────────────────────────


def _discover(module: types.ModuleType) -> dict[str, type[BaseModel]]:
    """Module-level model classes *defined* in ``module``, at any inheritance depth."""
    return {
        name: obj
        for name, obj in vars(module).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == module.__name__
    }


def _all_dtos() -> dict[str, type[BaseModel]]:
    return {**_discover(schemas_tutoring), **_discover(schemas_tutoring_admin)}


def _admin_dto_names() -> frozenset[str]:
    return frozenset(_spec_admin_names()) | ADMIN_DERIVED_DTO_NAMES


def _nested_models(annotation: object) -> Iterator[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in typing.get_args(annotation):
        yield from _nested_models(arg)


def _closure(roots: Iterable[type[BaseModel]]) -> set[type[BaseModel]]:
    """``roots`` plus every model reachable through field annotations."""
    seen: set[type[BaseModel]] = set()
    stack = list(roots)
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        for info in cls.model_fields.values():
            stack.extend(_nested_models(info.annotation))
    return seen


def _literal_values(annotation: object) -> tuple[object, ...]:
    if typing.get_origin(annotation) is typing.Literal:
        return typing.get_args(annotation)
    for arg in typing.get_args(annotation):
        values = _literal_values(arg)
        if values:
            return values
    return ()


def _field_literal(cls: type[BaseModel], field: str) -> tuple[object, ...]:
    return _literal_values(cls.model_fields[field].annotation)


def _all_literal_values(annotation: object) -> set[object]:
    """Every ``Literal`` value anywhere inside ``annotation``."""
    if typing.get_origin(annotation) is typing.Literal:
        return set(typing.get_args(annotation))
    values: set[object] = set()
    for arg in typing.get_args(annotation):
        values |= _all_literal_values(arg)
    return values


def _expected_own_fields(name: str) -> dict[str, SpecField]:
    """The own fields SPEC gives ``name``, with §b.3's one prose shorthand expanded.

    ``TutorProfileUpdateDTO``'s SPEC header reads "every field of Create,
    optional, plus:" — each Create field becomes ``T | None = None``.
    """
    spec = _spec_b3_classes()[name]
    if name != "TutorProfileUpdateDTO":
        return spec.fields
    assert "every field of Create, optional" in spec.header_comment
    expanded: dict[str, SpecField] = {}
    for field_name, field in _spec_b3_classes()["TutorProfileCreateDTO"].fields.items():
        nullable = field.annotation.endswith("|None")
        annotation = field.annotation if nullable else f"{field.annotation}|None"
        expanded[field_name] = SpecField(annotation, "None")
    return {**expanded, **spec.fields}


# ── Discovery and base class ──────────────────────────────────────────────────


def test_dto_discovery_matches_spec_b3_class_list() -> None:
    spec_classes = _spec_b3_classes()
    # Parser cross-check: one parsed class per `class ` line in the block.
    assert len(spec_classes) == len(re.findall(r"^class ", _b3_code(), re.MULTILINE))
    assert len(_spec_admin_names()) >= 1
    assert not ADMIN_DERIVED_DTO_NAMES & set(_spec_admin_names())

    public_module = set(_discover(schemas_tutoring))
    admin_module = set(_discover(schemas_tutoring_admin))
    assert public_module == set(spec_classes), (
        f"missing {sorted(set(spec_classes) - public_module)}, "
        f"unlisted {sorted(public_module - set(spec_classes))}"
    )
    assert admin_module == _admin_dto_names(), (
        f"missing {sorted(_admin_dto_names() - admin_module)}, "
        f"unlisted {sorted(admin_module - _admin_dto_names())}"
    )


def test_every_dto_is_apimodel_extra_forbid() -> None:
    dtos = _all_dtos()
    checked = 0
    for name, cls in dtos.items():
        assert issubclass(cls, ApiModel), f"{name} does not derive from lemely.web.schemas.ApiModel"
        assert cls.model_config.get("extra") == "forbid", name
        checked += 1
    assert checked == len(dtos) == len(_spec_b3_classes()) + len(_admin_dto_names())


# ── SPEC §b.3 conformance ─────────────────────────────────────────────────────


def test_every_spec_b3_dto_matches_spec_fields_types_and_defaults() -> None:
    checked = 0
    for name, spec in _spec_b3_classes().items():
        cls = getattr(schemas_tutoring, name)
        assert [base.__name__ for base in cls.__bases__] == [spec.base], name
        expected = _expected_own_fields(name)
        own = inspect.get_annotations(cls)
        assert set(own) == set(expected), f"{name}: {sorted(set(own) ^ set(expected))}"
        for field_name, field in expected.items():
            annotation = own[field_name]
            assert isinstance(annotation, str)
            assert _norm(annotation) == field.annotation, f"{name}.{field_name}"
            info = cls.model_fields[field_name]
            if field.default is None:
                assert info.is_required(), f"{name}.{field_name} should have no default"
            else:
                assert not info.is_required(), f"{name}.{field_name} should be optional"
                assert info.default == ast.literal_eval(field.default), f"{name}.{field_name}"
        checked += 1
    assert checked == len(_spec_b3_classes())


def test_literal_aliases_match_spec() -> None:
    aliases = _spec_b3_aliases()
    assert len(aliases) == len(re.findall(r"^\w+Lit = ", _b3_code(), re.MULTILINE))
    for name, values in aliases.items():
        assert typing.get_args(getattr(schemas_tutoring, name)) == values, name


def test_viewer_action_literal_includes_cancel_with_reason() -> None:
    """Row 18: a tutor inside 24 h of an accepted start is offered only this action."""
    actions = typing.get_args(schemas_tutoring.ViewerActionLit)
    assert actions == _spec_b3_aliases()["ViewerActionLit"]
    assert "cancel_with_reason" in actions
    assert "cancel" in actions
    allowed = schemas_tutoring.BookingDTO.model_fields["allowedActions"].annotation
    assert allowed == list[schemas_tutoring.ViewerActionLit]


def test_dto_literals_match_spec_a1_enum_values() -> None:
    enums = _spec_a1_enums()
    a6_kinds = re.search(r"kind=([^`]+)", _spec_b2_rows()["A6"]["Request"])
    assert a6_kinds
    moderation_kinds = tuple(k for k in a6_kinds.group(1).split("\\|") if k != "all")
    t, a = schemas_tutoring, schemas_tutoring_admin
    pairs: list[tuple[str, tuple[object, ...], tuple[str, ...]]] = [
        ("TutoringModeLit", typing.get_args(t.TutoringModeLit), enums["tutoringmode"]),
        (
            "EffectiveStateLit",
            typing.get_args(t.EffectiveStateLit),
            (*enums["bookingstate"], "awaiting_outcome"),
        ),
        (
            "TutorOwnProfileDTO.listingState",
            _field_literal(t.TutorOwnProfileDTO, "listingState"),
            enums["tutorlistingstate"],
        ),
        (
            "BookingDTO.cancelledBy",
            _field_literal(t.BookingDTO, "cancelledBy"),
            enums["bookingparty"],
        ),
        (
            "BookingDTO.completedBy",
            _field_literal(t.BookingDTO, "completedBy"),
            tuple(p for p in enums["bookingparty"] if p != "system"),
        ),
        (
            "AccessLogEntryDTO.action",
            _field_literal(t.AccessLogEntryDTO, "action"),
            enums["tutoraccessaction"],
        ),
        (
            "TutorReviewItemDTO.textState",
            _field_literal(t.TutorReviewItemDTO, "textState"),
            enums["moderationstate"],
        ),
        (
            "ReplyDTO.textState",
            _field_literal(t.ReplyDTO, "textState"),
            tuple(s for s in enums["moderationstate"] if s != "none"),
        ),
        (
            "ReportCreateDTO.targetType",
            _field_literal(t.ReportCreateDTO, "targetType"),
            enums["reporttargettype"],
        ),
        (
            "ReportCreateDTO.reason",
            _field_literal(t.ReportCreateDTO, "reason"),
            enums["reportreason"],
        ),
        (
            "AdminTutorDetailDTO.listingState",
            _field_literal(a.AdminTutorDetailDTO, "listingState"),
            enums["tutorlistingstate"],
        ),
        (
            "ReportDetailDTO.tutorListingState",
            _field_literal(a.ReportDetailDTO, "tutorListingState"),
            enums["tutorlistingstate"],
        ),
        (
            "AdminApprovalEventDTO.decision",
            _field_literal(a.AdminApprovalEventDTO, "decision"),
            enums["tutorapprovaldecision"],
        ),
        ("ModerationItemDTO.kind", _field_literal(a.ModerationItemDTO, "kind"), moderation_kinds),
        (
            "ReviewModerateDTO.decision",
            _field_literal(a.ReviewModerateDTO, "decision"),
            tuple(s for s in enums["moderationstate"] if s not in {"none", "pending"}),
        ),
        (
            "ReplyModerateDTO.decision",
            _field_literal(a.ReplyModerateDTO, "decision"),
            tuple(s for s in enums["moderationstate"] if s not in {"none", "pending"}),
        ),
        (
            "AdminReviewDTO.textState",
            _field_literal(a.AdminReviewDTO, "textState"),
            enums["moderationstate"],
        ),
        (
            "ReportItemDTO.targetType",
            _field_literal(a.ReportItemDTO, "targetType"),
            enums["reporttargettype"],
        ),
        ("ReportItemDTO.reason", _field_literal(a.ReportItemDTO, "reason"), enums["reportreason"]),
        ("ReportItemDTO.state", _field_literal(a.ReportItemDTO, "state"), enums["reportstate"]),
        (
            "ReportDetailDTO.reporterParty",
            _field_literal(a.ReportDetailDTO, "reporterParty"),
            tuple(p for p in enums["bookingparty"] if p in {"student", "parent", "tutor"}),
        ),
        (
            "ReportDetailDTO.resolution",
            _field_literal(a.ReportDetailDTO, "resolution"),
            enums["reportresolution"],
        ),
        (
            "ReportResolveDTO.resolution",
            _field_literal(a.ReportResolveDTO, "resolution"),
            enums["reportresolution"],
        ),
        (
            "AdminBookingSummaryDTO.effectiveState",
            _field_literal(a.AdminBookingSummaryDTO, "effectiveState"),
            (*enums["bookingstate"], "awaiting_outcome"),
        ),
    ]
    assert len(enums) >= 14  # the §a.1 table parsed (16 new types on 2026-10-25)
    for label, actual, expected in pairs:
        assert expected, f"{label}: SPEC enum not found"
        assert actual == expected, label


# ── Row 5b / §a.5: the open web sees the public card and nothing else ─────────


def test_public_dtos_carry_exactly_the_row_5b_fields() -> None:
    rows = _spec_b2_rows()
    roots = [
        getattr(schemas_tutoring, _dto_names(rows[r]["Response"])[0]) for r in ("P1", "P2", "P3")
    ]
    assert [root.__name__ for root in roots] == [
        "PublicDirectoryPageDTO",
        "PublicTutorCardDTO",
        "AreaListDTO",
    ]
    reachable = {cls.__name__: cls for cls in _closure(roots)}
    assert set(reachable) == set(ROW_5B_PUBLIC_FIELDS), sorted(
        set(reachable) ^ set(ROW_5B_PUBLIC_FIELDS)
    )
    for name, allowed in ROW_5B_PUBLIC_FIELDS.items():
        assert set(reachable[name].model_fields) == allowed, name
        # SPEC §b.3 and SPEC §a.5 agree on the same allowlist.
        assert _spec_all_fields(name) == allowed, name


def _spec_all_fields(name: str) -> set[str]:
    spec = _spec_b3_classes()[name]
    inherited = set() if spec.base == "ApiModel" else _spec_all_fields(spec.base)
    return inherited | set(_expected_own_fields(name))


# ── O29: no tutor users.id, no email, no parent-link presence ─────────────────


def test_idor_no_public_student_parent_dto_contains_tutor_user_id() -> None:
    """O29 / SC-19: a tutor is addressed by profile id only, outside admin DTOs."""
    own = _discover(schemas_tutoring)
    scanned = _closure(own.values())
    assert set(own.values()) <= scanned
    assert len(own) == len(_spec_b3_classes())
    guarded = (
        _b2_dtos_under("Public")
        | _b2_dtos_under("Logged-in directory")
        | _b2_dtos_under("Student")
        | _b2_dtos_under("Parent")
    )
    assert len(guarded) >= 10
    assert guarded <= {cls.__name__ for cls in scanned}, sorted(
        guarded - {cls.__name__ for cls in scanned}
    )
    offenders = [
        f"{cls.__name__}.{field}"
        for cls in scanned
        for field in cls.model_fields
        if "userid" in field.lower()
    ]
    assert not offenders, offenders


def test_no_tutoring_dto_contains_email_field_except_admin_account_email() -> None:
    """O29 / EM-5: only A2's ``accountEmail`` carries an address.

    ``AdminTutorPageDTO.emailDelivery`` matches the name but is the A1 delivery
    mode, typed to exactly the two values §b.2 A1 gives, so it cannot carry one.
    """
    scanned = _closure(_all_dtos().values())
    assert len(scanned) >= len(_all_dtos())
    found = {
        (cls.__name__, field)
        for cls in scanned
        for field in cls.model_fields
        if "email" in field.lower()
    }
    assert found == {
        ("AdminTutorDetailDTO", "accountEmail"),
        ("AdminTutorPageDTO", "emailDelivery"),
    }
    a1_modes = re.search(r"emailDelivery: (.+?)`", _spec_b2_rows()["A1"]["Response"])
    assert a1_modes
    assert _field_literal(schemas_tutoring_admin.AdminTutorPageDTO, "emailDelivery") == tuple(
        re.findall(r'"(\w+)"', a1_modes.group(1))
    )
    account_email = schemas_tutoring_admin.AdminTutorDetailDTO.model_fields["accountEmail"]
    assert account_email.annotation is str


def test_tutor_facing_dto_field_names_never_name_parents() -> None:
    """SC-9 / O29, field names only: no tutor-facing DTO has a parent-shaped field.

    This checks names, not values, so it does not prove SC-9 on its own.
    ``BookingDTO.requestedBy``, ``cancelledBy`` and ``completedBy`` may hold
    ``"parent"`` in the DTO type, and ``BookingDTO`` reaches tutors (T9-T15).
    The remaining obligation is the builder's: for a tutor viewer it maps
    ``"parent"`` to ``"student"`` in those three fields, so no tutor learns that
    a student has a linked parent (SC-9).
    ``test_parent_literal_value_only_in_the_three_booking_party_fields`` pins
    where that value can appear until the builder and its own test exist.
    """
    own = _discover(schemas_tutoring)
    scanned = _closure(own.values())
    assert len(own) == len(_spec_b3_classes())
    tutor_facing = _b2_dtos_under("Tutor") | _b2_dtos_under("Safety")
    assert len(tutor_facing) >= 10
    assert tutor_facing <= {cls.__name__ for cls in scanned}, sorted(
        tutor_facing - {cls.__name__ for cls in scanned}
    )
    offenders = [
        f"{cls.__name__}.{field}"
        for cls in scanned
        for field in cls.model_fields
        if "parent" in field.lower()
    ]
    assert not offenders, offenders


def test_parent_literal_value_only_in_the_three_booking_party_fields() -> None:
    """SC-9: the only places a non-admin DTO can say ``"parent"`` by value.

    No builder exists yet (T13, T17, T18 write them). Whoever writes the
    ``BookingDTO`` builder must map ``"parent"`` to ``"student"`` in each of
    these three fields for a tutor viewer. A new literal that can hold
    ``"parent"`` on any non-admin DTO fails here, so the obligation is
    revisited rather than silently widened.
    """
    own = _discover(schemas_tutoring)
    assert len(own) == len(_spec_b3_classes())
    assert "BookingDTO" in _b2_dtos_under("Tutor")
    scanned = _closure(own.values())
    found = {
        (cls.__name__, field)
        for cls in scanned
        for field, info in cls.model_fields.items()
        if "parent" in _all_literal_values(info.annotation)
    }
    assert found == PARENT_VALUED_BOOKING_FIELDS
    booking = schemas_tutoring.BookingDTO
    assert _field_literal(booking, "requestedBy") == ("student", "parent")
    assert _field_literal(booking, "cancelledBy") == (
        "student",
        "parent",
        "tutor",
        "platform_admin",
        "system",
    )
    assert _field_literal(booking, "completedBy") == (
        "student",
        "parent",
        "tutor",
        "platform_admin",
    )


# ── O31: indexable ────────────────────────────────────────────────────────────


def test_indexable_only_on_public_card_own_profile_and_admin() -> None:
    """O31: P2, the tutor's own profile and A2 serve it; T3's body sets it."""
    rows = _spec_b2_rows()
    allowed = set(re.findall(r"`(\w+DTO)`", _spec_c3_row("O31")))
    allowed.add(_dto_names(rows["A2"]["Response"])[0])
    assert "indexable" in rows["T3"]["Request"]
    allowed.add(_dto_names(rows["T3"]["Request"])[0])
    assert allowed == {
        "PublicTutorCardDTO",
        "TutorOwnProfileDTO",
        "AdminTutorDetailDTO",
        "TutorProfileUpdateDTO",
    }
    scanned = _closure(_all_dtos().values())
    assert len(scanned) >= len(_all_dtos())
    carriers = {cls.__name__ for cls in scanned if "indexable" in cls.model_fields}
    assert carriers == allowed


# ── ADR-T03 / O15 / §a.5: admin DTOs ──────────────────────────────────────────


def test_no_admin_dto_contains_student_detail_fields() -> None:
    """ADR-T03 action 3: no admin path into any part of ``StudentDetailDTO``.

    Two checks: no admin DTO reaches a model of the ``StudentDetailDTO`` family
    through a field type, and no admin field reuses one of its top-level names.
    ``subjects`` is exempt when it is the tutor's taught subjects
    (``list[SubjectRefDTO]``, from ``TutorCardDTO``), never subject predictions.
    """
    admin = _discover(schemas_tutoring_admin)
    assert len(admin) == len(_admin_dto_names())
    scanned = _closure(admin.values())
    analytics = _closure([StudentDetailDTO])
    assert len(analytics) >= 2
    assert not scanned & analytics, sorted(cls.__name__ for cls in scanned & analytics)
    student_detail_names = set(StudentDetailDTO.model_fields)
    for cls in scanned:
        for field, info in cls.model_fields.items():
            if field not in student_detail_names:
                continue
            assert field == "subjects", f"{cls.__name__}.{field}"
            assert info.annotation == list[schemas_tutoring.SubjectRefDTO], cls.__name__


def test_admin_only_fields_live_only_on_their_admin_dto() -> None:
    scanned = _closure(_all_dtos().values())
    admin_names = {cls.__name__ for cls in _discover(schemas_tutoring_admin).values()}
    for field, owner in ADMIN_ONLY_FIELD_OWNERS.items():
        carriers = {cls.__name__ for cls in scanned if field in cls.model_fields}
        assert carriers == {owner}, f"{field}: {sorted(carriers)}"
        assert owner in admin_names
    admin_closure = _closure(_discover(schemas_tutoring_admin).values())
    leaked = [
        f"{cls.__name__}.{field}"
        for cls in admin_closure
        for field in cls.model_fields
        if field in NEVER_ON_ADMIN_DTOS
    ]
    assert not leaked, leaked
    placed = {cls.__name__ for cls in admin_closure if "locationDetail" in cls.model_fields}
    assert placed == ADMIN_LOCATION_OWNERS, sorted(placed)


def test_admin_tutor_detail_carries_every_own_profile_field() -> None:
    """§b.3: ``AdminTutorDetailDTO`` = TutorOwnProfileDTO fields + the admin fields.

    The admin fields are read from SPEC §b.3's own wording. ``evidence`` is
    the one field whose type changes: the admin row adds the signed URL
    (``AdminEvidenceDTO``).
    """
    extra = _spec_admin_detail_extra_fields()
    assert "evidence" in extra
    own_profile = schemas_tutoring.TutorOwnProfileDTO.model_fields
    detail = schemas_tutoring_admin.AdminTutorDetailDTO.model_fields
    assert set(detail) == set(own_profile) | extra, sorted(set(detail) ^ (set(own_profile) | extra))
    for name, info in own_profile.items():
        if name == "evidence":
            continue
        assert detail[name].annotation == info.annotation, name
        assert detail[name].is_required() == info.is_required(), name
    assert detail["evidence"].annotation == list[schemas_tutoring_admin.AdminEvidenceDTO]


def test_admin_evidence_signed_url_is_null_outside_a2() -> None:
    """O17: signed URLs are issued on A2 only, yet A3-A5 and A12 return the same DTO."""
    rows = _spec_b2_rows()
    returning_detail = {
        route
        for route, row in rows.items()
        if _dto_names(row["Response"])[:1] == ["AdminTutorDetailDTO"]
    }
    assert "A2" in returning_detail
    assert returning_detail - {"A2"}, "only A2 returns the detail; signedUrl could be required"
    assert "A2 only" in _spec_c3_row("O17")
    annotation = schemas_tutoring_admin.AdminEvidenceDTO.model_fields["signedUrl"].annotation
    assert type(None) in typing.get_args(annotation)
    assert set(schemas_tutoring_admin.AdminEvidenceDTO.model_fields) == set(
        schemas_tutoring.EvidenceDTO.model_fields
    ) | {"signedUrl"}


def test_moderation_dtos_carry_the_spec_text_revision() -> None:
    """RF-7: A6 shows each text's revision and A7 must send it back (§b.3 admin notes).

    The field names, their required-ness and the hash length are read from SPEC
    §b.3's wording; A8 has no revision because a reply cannot be edited.
    """
    a = schemas_tutoring_admin
    item_note = _spec_admin_note("ModerationItemDTO")
    assert item_note.startswith("+ "), item_note  # added to the derived A6 item fields
    added = _note_fields(item_note)
    assert added == {"revision"}
    assert added <= set(a.ModerationItemDTO.model_fields), sorted(a.ModerationItemDTO.model_fields)
    for name in added:
        assert a.ModerationItemDTO.model_fields[name].annotation is str
        assert a.ModerationItemDTO.model_fields[name].is_required()

    review_note = _spec_admin_note("ReviewModerateDTO")
    review_fields = _note_fields(review_note)
    assert set(a.ReviewModerateDTO.model_fields) == review_fields == {"decision", "revision"}
    assert "required" in review_note.partition(":")[2]
    assert all(a.ReviewModerateDTO.model_fields[name].is_required() for name in review_fields)
    assert a.ReviewModerateDTO.model_fields["revision"].annotation is str

    reply_note = _spec_admin_note("ReplyModerateDTO")
    assert set(a.ReplyModerateDTO.model_fields) == _note_fields(reply_note) == {"decision"}

    length = re.search(r"first (\d+) hex characters of the SHA-256", item_note)
    assert length, item_note
    for text in ("Clear and patient.", "", "شكرا"):
        expected = hashlib.sha256(text.encode("utf-8")).hexdigest()[: int(length.group(1))]
        assert text_revision(text) == expected


def test_every_field_sits_on_a_line_the_ts_parity_parser_reads() -> None:
    """The TS parity test cannot drop a field from both sides unnoticed.

    ``tutoringTypesParity.test.ts`` parses these modules as text, one field per
    line of the ``TS_PARITY_FIELD_LINE`` shape. A field it missed would vanish
    from its parsed Python and could be missing from the TS file too, and
    parity would still pass. The vitest counts fields against SPEC §b.3, which
    covers the §b.3 classes only (the web CI job has no Python for an AST, and
    SPEC gives no admin fields). Here the Python AST, independent of that
    regex, finds every annotated field in both modules, admin included,
    matches it to pydantic's own annotations, and checks its line has the shape
    the vitest reads.
    """
    checked = 0
    for module in (schemas_tutoring, schemas_tutoring_admin):
        assert module.__file__
        source = Path(module.__file__).read_text(encoding="utf-8")
        lines = source.splitlines()
        classes = [node for node in ast.parse(source).body if isinstance(node, ast.ClassDef)]
        assert {node.name for node in classes} == set(_discover(module))
        for node in classes:
            fields = [
                (stmt.target.id, stmt.lineno)
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            ]
            own = list(inspect.get_annotations(getattr(module, node.name)))
            assert [name for name, _ in fields] == own, node.name
            for name, lineno in fields:
                line = lines[lineno - 1]
                shape = TS_PARITY_FIELD_LINE.match(line)
                assert shape, f"{node.name} line {lineno}: {line!r}"
                assert shape.group(1) == name, f"{node.name}: {line!r}"
                checked += 1
    assert checked == sum(len(inspect.get_annotations(cls)) for cls in _all_dtos().values())
    assert checked > len(_all_dtos())


def test_spec_b2_parser_sees_every_route() -> None:
    """Non-vacuity for every §b.2-derived check above: SPEC counts 70 routes."""
    count = re.search(r"\*\*Route count: (\d+)\*\*", _spec_text())
    assert count
    assert len(_spec_b2_rows()) == int(count.group(1))

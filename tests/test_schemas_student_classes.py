"""Field-set pin for the ``GET /api/student/classes`` DTOs (P5.8 chunk C, D5.14 §1).

Same control the leaderboard and friends DTOs carry (D5.1 §0): introspect the
declared field sets rather than eyeballing the source, so a well-meaning future
addition — "just the class average, it's useful" — fails a test instead of
reaching the wire.

A class list is a *navigation* surface: it exists so S-29 can name a class
scope. Nothing here is an attainment surface, and it must not quietly become
one.
"""

from __future__ import annotations

from lemely.web.schemas_student_classes import StudentClassDTO, StudentClassListDTO

_FORBIDDEN_SUBSTRINGS = ("mark", "percent", "grade", "accuracy", "score", "confidence", "rank")

_EXPECTED_CLASS_FIELDS = {"classId", "name", "subjectCode", "schoolName"}


class TestNoAttainmentShapedFields:
    def test_class_dto_field_set_is_exactly_identity_subject_and_school(self) -> None:
        assert set(StudentClassDTO.model_fields) == _EXPECTED_CLASS_FIELDS

    def test_class_dto_has_no_field_matching_a_forbidden_substring(self) -> None:
        lowered = {name.lower() for name in StudentClassDTO.model_fields}
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            matches = [name for name in lowered if forbidden in name]
            assert not matches, (
                f"StudentClassDTO has a field matching forbidden substring {forbidden!r}: {matches}"
            )

    def test_list_dto_carries_only_the_classes(self) -> None:
        assert set(StudentClassListDTO.model_fields) == {"classes"}


class TestNullableFieldsStayNullable:
    def test_subject_code_admits_none(self) -> None:
        """A class its teacher never scoped to a subject has no code at all."""
        annotation = StudentClassDTO.model_fields["subjectCode"].annotation
        assert type(None) in getattr(annotation, "__args__", ())

    def test_school_name_admits_none(self) -> None:
        """An independent teacher's class genuinely has no school (D5.14 §1)."""
        annotation = StudentClassDTO.model_fields["schoolName"].annotation
        assert type(None) in getattr(annotation, "__args__", ())

    def test_a_school_less_class_constructs_without_a_placeholder(self) -> None:
        row = StudentClassDTO(
            classId="c1", name="Tutoring group", subjectCode=None, schoolName=None
        )
        assert row.schoolName is None
        assert row.subjectCode is None


class TestEmptyListIsRepresentable:
    def test_no_classes_is_a_valid_response(self) -> None:
        """The empty state is an answer, not an error — it must construct."""
        assert StudentClassListDTO(classes=[]).classes == []

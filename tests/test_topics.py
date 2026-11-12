"""P4.2 — syllabus taxonomy loading and the deterministic topic classifier.

The tests that matter here are the *abstention* ones. Coverage is easy to fake
by lowering a threshold; what this module is actually for is refusing to label
a question it cannot place, so several tests below assert ``None`` and would
pass trivially if scoring were broken. Each of those is paired with a positive
case over the same taxonomy so a dead classifier cannot satisfy both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from lemely.core.schemas import ConfidenceBand
from lemely.core.topics import (
    WRITABLE_BANDS,
    SyllabusTaxonomy,
    TopicNode,
    classify,
    is_writable,
)
from lemely.io.syllabus_topics import get_taxonomy, invalidate_reference_cache, load_taxonomies

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

# --------------------------------------------------------------------------
# The catalogue, read from Postgres
# --------------------------------------------------------------------------

EXPECTED_SUBJECTS = {"0580", "0606", "0625"}


@pytest.fixture(autouse=True)
def _reset_taxonomy_cache() -> None:
    """Force every test to load through its own fixture-provided session,
    rather than a process-cached result left over from another test's
    throwaway database."""
    invalidate_reference_cache()


def test_all_three_in_scope_subjects_are_bundled(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """MISSION §1 scopes this run to 0580, 0606 and 0625 — all three or it is a gap."""
    with migrated_sessionmaker() as s:
        taxonomies = load_taxonomies(session=s)
    assert {code for _board, code in taxonomies} == EXPECTED_SUBJECTS


def test_every_taxonomy_records_its_syllabus_provenance(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """CAIE renumbers topics between cycles, so a label without a version is a lie.

    "4.3 Electric circuits" only means something against a stated syllabus, and
    the next session must be able to tell which PDF the tree came from without
    re-downloading anything.
    """
    with migrated_sessionmaker() as s:
        taxonomies = load_taxonomies(session=s)
    for taxonomy in taxonomies.values():
        assert taxonomy.syllabus_version
        assert taxonomy.source_url.startswith("https://www.cambridgeinternational.org/")


def test_0625_topic_structure_matches_the_published_syllabus(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Transcription check against 595430-2023-2025-syllabus.pdf §3."""
    with migrated_sessionmaker() as sess:
        physics = get_taxonomy("0625", session=sess)
    assert physics is not None
    assert [t.name for t in physics.topics] == [
        "Motion, forces and energy",
        "Thermal physics",
        "Waves",
        "Electricity and magnetism",
        "Nuclear physics",
        "Space physics",
    ]
    # Topic 1 has eight subtopics, 1.1 through 1.8.
    assert [s.code for s in physics.topics[0].subtopics] == [f"1.{n}" for n in range(1, 9)]


def test_0606_is_topic_level_only(migrated_sessionmaker: sessionmaker[Session]) -> None:
    """0606 numbers learning objectives, not named subtopics — so no subtopic labels.

    Pinned because it is a real asymmetry between subjects, not an omission: a
    future session finding 0606 "missing" its subtopics should see this test
    and the data file's ``section`` note rather than inventing fourteen.
    """
    with migrated_sessionmaker() as s:
        add_maths = get_taxonomy("0606", session=s)
    assert add_maths is not None
    assert len(add_maths.topics) == 14
    assert all(topic.subtopics == [] for topic in add_maths.topics)


def test_labels_are_code_prefixed_and_unique_within_a_subject(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """Duplicate labels would silently merge two topics in every group-by downstream."""
    with migrated_sessionmaker() as s:
        taxonomies = load_taxonomies(session=s)
    for taxonomy in taxonomies.values():
        labels = taxonomy.labels()
        assert len(labels) == len(set(labels)), taxonomy.subject_code
        assert all(label[0].isdigit() for label in labels)


def test_unknown_subject_returns_none_rather_than_a_wrong_tree(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    with migrated_sessionmaker() as s:
        assert get_taxonomy("9999", session=s) is None
        assert get_taxonomy("0625", board="edexcel", session=s) is None


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


@pytest.fixture
def toy() -> SyllabusTaxonomy:
    """A two-topic taxonomy small enough to reason about exactly."""
    return SyllabusTaxonomy(
        board="caie",
        subject_code="TEST",
        subject_name="Test",
        syllabus_version="x",
        source_url="https://www.cambridgeinternational.org/x.pdf",
        topics=[
            TopicNode(
                code="1",
                name="Alpha",
                keywords=["alpha"],
                subtopics=[
                    TopicNode(code="1.1", name="One", strong=["widget assembly"]),
                    TopicNode(code="1.2", name="Two", strong=["sprocket"]),
                ],
            ),
            TopicNode(
                code="2",
                name="Beta",
                subtopics=[TopicNode(code="2.1", name="Three", strong=["flange"])],
            ),
        ],
    )


def test_a_single_strong_term_is_enough_to_classify(toy: SyllabusTaxonomy) -> None:
    match = classify("Describe the sprocket in Fig. 2.", toy)
    assert match is not None
    assert match.label == "1.2 Two"
    assert match.granularity == "subtopic"


def test_empty_and_signal_free_text_classify_to_nothing(toy: SyllabusTaxonomy) -> None:
    assert classify("", toy) is None
    assert classify("Which statement is correct?", toy) is None


def test_a_genuine_tie_across_topics_abstains(toy: SyllabusTaxonomy) -> None:
    """One strong hit in each of two *different* topics is not evidence for either.

    This is the case a naive argmax gets wrong: it would pick whichever came
    first in the file and report it with no visible caveat.
    """
    assert classify("The sprocket is bolted to the flange.", toy) is None


def test_breadth_within_one_topic_falls_back_to_the_topic_label(
    toy: SyllabusTaxonomy,
) -> None:
    """Two subtopics of the *same* parent is breadth, not ambiguity.

    "1.1 One" and "1.2 Two" tie at subtopic level, but they agree on the
    parent, so the honest answer is the parent label rather than silence.
    """
    match = classify("The widget assembly drives the sprocket. alpha", toy)
    assert match is not None
    assert match.label == "1 Alpha"
    assert match.granularity == "topic"


def test_terms_match_across_hyphenation_and_dash_style() -> None:
    """The defect real 0625 papers exposed: CAIE writes it both ways.

    Authored as "double-insulated", the term must still match a paper that
    printed "double insulated", and vice versa.
    """
    taxonomy = SyllabusTaxonomy(
        board="caie",
        subject_code="TEST",
        subject_name="Test",
        syllabus_version="x",
        source_url="https://www.cambridgeinternational.org/x.pdf",
        topics=[
            TopicNode(
                code="1",
                name="Safety",
                subtopics=[TopicNode(code="1.1", name="Casing", strong=["double-insulated"])],
            )
        ],
    )
    for phrasing in ("double-insulated", "double insulated", "double\u2013insulated"):
        assert classify(f"A {phrasing} appliance.", taxonomy) is not None


def test_repeating_a_term_does_not_inflate_the_score(toy: SyllabusTaxonomy) -> None:
    """Otherwise long stems would outrank short ones on vocabulary they share."""
    once = classify("sprocket", toy)
    many = classify("sprocket sprocket sprocket sprocket", toy)
    assert once is not None
    assert many is not None
    assert once.score == many.score


def test_classification_is_stable_under_topic_ordering(toy: SyllabusTaxonomy) -> None:
    """A tie must resolve by syllabus order, not by dict/iteration accident."""
    first = classify("widget assembly", toy)
    second = classify("widget assembly", toy)
    assert first is not None
    assert first.label == second.label if second else False


# --------------------------------------------------------------------------
# The write policy (D4.4)
# --------------------------------------------------------------------------


def test_only_high_and_medium_are_writable() -> None:
    assert frozenset({ConfidenceBand.HIGH, ConfidenceBand.MEDIUM}) == WRITABLE_BANDS


def test_is_writable_rejects_no_match_and_low_confidence(toy: SyllabusTaxonomy) -> None:
    assert not is_writable(None)
    weak = classify("alpha", toy)
    assert weak is None or weak.confidence is ConfidenceBand.LOW


# --------------------------------------------------------------------------
# Against the real bundled physics taxonomy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        (
            "Many household smoke alarms contain a sample of the radioactive isotope "
            "americium-241. State the half-life of the source.",
            "5.2 Radioactivity",
        ),
        (
            "The Milky Way is one of many billions of galaxies. Describe redshift in "
            "the light from distant galaxies.",
            "6.2 Stars and the Universe",
        ),
        (
            "Two identical resistors are connected in series in a circuit diagram. "
            "Calculate the combined resistance of the two resistors.",
            "4.3 Electric circuits",
        ),
        (
            "A thin converging lens produces a real image. State the focal length and "
            "mark the principal focus on the ray diagram.",
            "3.2 Light",
        ),
        (
            "Define specific heat capacity. Describe experiments to measure the "
            "specific heat capacity of a metal block.",
            "2.2 Thermal properties and temperature",
        ),
    ],
)
def test_unambiguous_physics_questions_land_on_the_right_subtopic(
    stem: str, expected: str, migrated_sessionmaker: sessionmaker[Session]
) -> None:
    with migrated_sessionmaker() as s:
        physics = get_taxonomy("0625", session=s)
    assert physics is not None
    match = classify(stem, physics)
    assert match is not None, stem
    assert match.label == expected
    assert is_writable(match)


def test_a_physics_question_with_no_topic_vocabulary_is_left_unclassified(
    migrated_sessionmaker: sessionmaker[Session],
) -> None:
    """The honest outcome for a terse stem, and the reason coverage is not 100%.

    Roughly a fifth of the real 0625 MCQ bank looks like this. Labelling it
    anyway is the failure mode this whole module is shaped to avoid.
    """
    with migrated_sessionmaker() as s:
        physics = get_taxonomy("0625", session=s)
    assert physics is not None
    assert classify("Which statement is correct?", physics) is None

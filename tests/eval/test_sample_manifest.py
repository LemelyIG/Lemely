"""Pre-committed relabel-sample selection (#98, DA2/#51).

Rule is pre-committed now; membership is computed only after #47 completes.
This test file works entirely against synthetic leaf populations — it never
reads a real leaf population and asserts no membership is shipped in this
change (see ``eval/relabel_manifest.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

from lemely.eval.sample_manifest import LeafForSampling, select_relabel_sample

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _synthetic_population(n_per_band: int = 40) -> list[LeafForSampling]:
    leaves: list[LeafForSampling] = []
    for band in ("1", "2", "3+"):
        for i in range(n_per_band):
            leaves.append(
                {"paper_id": f"paper-{i % 4}", "question_id": f"{band}-q{i}", "mark_band": band}
            )
    return leaves


class TestDeterminism:
    def test_same_salt_and_population_gives_byte_identical_membership(self) -> None:
        population = _synthetic_population()
        first = select_relabel_sample(population, relabel_salt="salt-alpha")
        second = select_relabel_sample(population, relabel_salt="salt-alpha")
        assert first == second

    def test_membership_is_order_independent(self) -> None:
        population = _synthetic_population()
        shuffled = list(reversed(population))
        original = select_relabel_sample(population, relabel_salt="salt-alpha")
        reordered = select_relabel_sample(shuffled, relabel_salt="salt-alpha")
        assert original == reordered

    def test_different_salt_gives_a_different_membership_set(self) -> None:
        population = _synthetic_population()
        first = select_relabel_sample(population, relabel_salt="salt-alpha")
        second = select_relabel_sample(population, relabel_salt="salt-beta")
        assert first != second, "the salt must be load-bearing, not decorative"


class TestNoRng:
    def test_module_source_contains_no_random_or_shuffle(self) -> None:
        import lemely.eval.sample_manifest as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "random" not in source.lower()
        assert "shuffle" not in source.lower()


class TestStratumProportionality:
    def test_each_mark_band_contributes_its_own_proportional_share(self) -> None:
        population = _synthetic_population(n_per_band=40)
        selected = select_relabel_sample(population, relabel_salt="salt-alpha", fraction=0.10)

        per_band_selected: dict[str, int] = {"1": 0, "2": 0, "3+": 0}
        for leaf in population:
            if (leaf["paper_id"], leaf["question_id"]) in selected:
                per_band_selected[leaf["mark_band"]] += 1

        # 10% of 40 == 4 per band, proportional -- not one band starved to
        # fill another's quota.
        assert per_band_selected == {"1": 4, "2": 4, "3+": 4}

    def test_unequal_band_sizes_stay_proportional_per_stratum(self) -> None:
        population: list[LeafForSampling] = (
            [{"paper_id": "p1", "question_id": f"1-q{i}", "mark_band": "1"} for i in range(50)]
            + [{"paper_id": "p1", "question_id": f"2-q{i}", "mark_band": "2"} for i in range(30)]
            + [{"paper_id": "p1", "question_id": f"3-q{i}", "mark_band": "3+"} for i in range(20)]
        )
        selected = select_relabel_sample(population, relabel_salt="salt-alpha", fraction=0.10)

        per_band_selected: dict[str, int] = {"1": 0, "2": 0, "3+": 0}
        for leaf in population:
            if (leaf["paper_id"], leaf["question_id"]) in selected:
                per_band_selected[leaf["mark_band"]] += 1

        assert per_band_selected == {"1": 5, "2": 3, "3+": 2}


class TestManifestRoundTrip:
    def test_committed_manifest_salt_round_trips_through_selection(self) -> None:
        manifest_path = _REPO_ROOT / "eval" / "relabel_manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert isinstance(manifest["relabel_salt"], str)
        assert len(manifest["relabel_salt"]) > 0
        # No membership list is shipped -- #47 has not completed.
        assert manifest.get("membership") is None
        assert manifest.get("membership_computed") is False

        population = _synthetic_population()
        # The committed salt must be usable by the real selection function.
        result = select_relabel_sample(population, relabel_salt=manifest["relabel_salt"])
        assert isinstance(result, set)
        assert len(result) > 0


class TestLeafIdentityIsPaperAndQuestion:
    """Leaf identity is ``(paper_id, question_id)`` (DA6), never the bare id.

    The regression these guard against is the D18 narrowed denominator:
    ``1a`` occurs in every paper, so a sample keyed on ``question_id`` alone
    would treat one leaf per paper as a single selection unit.
    """

    def test_same_question_id_in_two_papers_is_two_distinct_leaves(self) -> None:
        population: list[LeafForSampling] = [
            {"paper_id": f"paper-{p}", "question_id": "1a", "mark_band": "1"} for p in range(20)
        ]
        selected = select_relabel_sample(population, relabel_salt="salt-alpha", fraction=0.50)

        # Keyed on question_id alone every one of these collapses to "1a" and
        # the result would hold exactly one element.
        assert len(selected) == 10
        assert all(isinstance(leaf, tuple) and len(leaf) == 2 for leaf in selected)
        assert {leaf[1] for leaf in selected} == {"1a"}
        assert len({leaf[0] for leaf in selected}) == 10

    def test_paper_id_is_load_bearing_in_the_rank(self) -> None:
        """Moving a leaf to another paper changes its rank, not just its label."""
        in_paper_a: list[LeafForSampling] = [
            {"paper_id": "paper-a", "question_id": f"q{i}", "mark_band": "1"} for i in range(40)
        ]
        in_paper_b: list[LeafForSampling] = [
            {"paper_id": "paper-b", "question_id": f"q{i}", "mark_band": "1"} for i in range(40)
        ]
        a_ids = {q for _, q in select_relabel_sample(in_paper_a, relabel_salt="salt-alpha")}
        b_ids = {q for _, q in select_relabel_sample(in_paper_b, relabel_salt="salt-alpha")}
        assert a_ids != b_ids


class TestNoStratumIsStarvedToZero:
    def test_a_stratum_of_four_still_contributes_a_leaf_at_ten_percent(self) -> None:
        """``round(4 * 0.1)`` is 0; the docstring promises no starved stratum.

        A stratum dropped to zero disappears from the agreement figure
        entirely while the denominator still claims to be stratified.
        """
        population: list[LeafForSampling] = [
            {"paper_id": "p1", "question_id": f"big-{i}", "mark_band": "1"} for i in range(100)
        ] + [{"paper_id": "p1", "question_id": f"small-{i}", "mark_band": "3+"} for i in range(4)]

        selected = select_relabel_sample(population, relabel_salt="salt-alpha", fraction=0.10)

        small = {q for _, q in selected if q.startswith("small-")}
        assert len(small) == 1, "a non-empty stratum must never round away to nothing"

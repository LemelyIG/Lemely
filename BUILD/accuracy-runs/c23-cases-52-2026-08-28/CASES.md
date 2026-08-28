# C23 — concrete corpus cases for #52's three seed rulings

**Zero spend.** Deterministic reads of the 289 committed
`corpus/mark-schemes/*.json` only. No Gemini, no network.

**These are cases, not recommendations.** C23 declined the "only cases that
change the mark outcome" narrowing on the ground that pre-filtering by mark
impact would be the agent making the judgment the ruling exists to capture — so
the selection rule below is **mechanical and stated**: within each category,
de-duplicate identical answer text, then take the first five by scheme stem in
sorted order. Nothing was ranked by how interesting or how consequential it
looked, and no ruling is drafted or hinted at.

**How common each is, so the sample is not mistaken for the population:**

| category | instances | distinct texts |
|---|---|---|
| ECF / follow-through | **27** | 27 |
| `oe` (or equivalent) | **908** | 820 |
| list-rule, more options listed than the tariff | **135** | 51 |

---

## 1. ECF / follow-through

Every instance in the corpus takes the same form: *"Strict FT their &lt;earlier
answer&gt;"*. The scheme directs the marker to accept an answer that is wrong in
absolute terms but correct given the candidate's own earlier (wrong) value.

| scheme | question | tariff | text |
|---|---|---|---|
| `0580_m22_ms_42` | `5e_i` | 1 | Strict FT their median reading |
| `0580_m22_ms_42` | `5e_ii` | 1 | Strict FT their UQ reading |
| `0580_m22_ms_42` | `5e_iii` | 2 | Strict FT their reading at 40th percentile |
| `0580_m22_ms_42` | `5e_iv` | 2 | Strict FT their reading at 400 – their reading at 250 |
| `0580_s19_ms_43` | `3c_ii` | 1 | Strict FT their (c)(i) |

**The decision this needs from you.** Awarding these requires reading the
candidate's *earlier* answer and re-deriving what would be correct from it. It is
a cross-question dependency: `5e_iv` depends on two earlier readings, and
`3c_ii` on `3c_i`.

---

## 2. `oe` — "or equivalent"

The largest category by an order of magnitude (908 instances). The marker is
told an answer other than the printed one may be accepted, without the boundary
of "equivalent" being stated.

| scheme | question | tariff | point marks | text |
|---|---|---|---|---|
| `0580_m19_ms_12` | `2` | 1 | 1 | `[0].03 oe` |
| `0580_m19_ms_12` | `15b` | 1 | 1 | `4100000 oe` |
| `0580_m19_ms_12` | `25` | 4 | 1 | `25 12 75 10 their × or their ÷ oe 8 5 24 24` |
| `0580_m19_ms_12` | `25` | 4 | 1 | `300 their oe 40` |
| `0580_m19_ms_22` | `9` | 2 | 2 | `1 [y = ] (x−4) oe final answer 4` |

**The decision this needs from you.** The span runs from narrow numeric
equivalence (is `0.030` the same answer as `[0].03`? is `4.1 × 10⁶` the same as
`4100000`?) to algebraic equivalence (`9`, where any rearrangement of a linear
equation is presumably intended) — and cases like `25`, where `oe` sits inside a
partially-linearised expression and it is not evident from the text alone what
the equivalence class even is.

---

## 3. List rule — more options listed than the tariff allows

The scheme prints *"any two from"* and then lists three or four bullets. Note
column `bullets` against column `tariff`.

| scheme | question | tariff | point marks | bullets | text |
|---|---|---|---|---|---|
| `0625_m21_ms_42` | `3c` | 2 | 2 | **4** | any two from: • air pollution / harmful gases / acid rain • CO₂ / greenhouse gases / contribution to global warming • not renewable • damage from mining / drilling |
| `0625_m21_ms_42` | `6a` | 2 | **1** | 3 | Any two correct rays from • from O through optical centre • from O parallel to principal axis … through F • from F through O … parallel to principal axis |
| `0625_s23_ms_42` | `5a_iii` | 1 | 1 | 2 | any one from: • energy transferred to furniture / walls / objects • energy transferred through windows / doors / floor / ceiling |
| `0625_s23_ms_42` | `9d` | 2 | 2 | **4** | any two from: • limit time of exposure • store sources in lead boxes • keep distance from sources • avoid contact OR use tongs OR wear gloves |
| `0625_s23_ms_51` | `3d` | 1 | 1 | **4** | any one from: • view bases of pins • place pins as far apart as possible • ensure pins are vertical • sharp pencil / thin lines / thin pins |

**The decision this needs from you.** Two things are visible in the data and are
reported as facts rather than as arguments:

1. **The tariff caps the award, and the bullet count exceeds it** — 4 options for
   2 marks, 4 for 1. What happens when a candidate gives three correct bullets
   for a 2-mark question, and what happens when they give two correct and one
   wrong, are not stated by the scheme text.
2. **`0625_m21_ms_42 6a` is stored inconsistently with the others** — tariff 2
   but the answer point carries **1** mark, where `3c` and `9d` carry 2. It is
   recorded here because it is in the data, not as a claim about which is right.

---

**Reproduce:** `pull_cases.py` (writes `cases.json`). Nothing here is a
recommendation, and the H8 ruling log stays empty until you rule.

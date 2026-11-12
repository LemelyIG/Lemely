# Design canvas notes

The audit dossier (`docs/superpowers/specs/2026-09-10-audit-dossier-remediation-ledger.md`'s
source artifact, "Lemely Audit Dossier", 9 Sep 2026) reviewed the pre-redesign
exploration canvas alongside production and `DESIGN.md`. Five of its findings
turn out to be the canvas describing something this repo's design system
already supersedes, not a gap production needs to fill. This document is the
written, findable decision each of those five ledger rows points at.

The canvas artifact itself is external to this repository (a Claude.ai
artifact referenced by URL from the ledger, not checked in as text), so the
sections below cite what is known and authoritative — `DESIGN.md` and
`PRODUCT.md` — rather than re-quoting the canvas verbatim.

## Device limit

**Ledger id:** `trust-ops-device-limit-count-divergence`

The canvas's device-management screens implied a different concurrent-device
cap than the product ships. `PRODUCT.md:71` is authoritative and unambiguous:

> Maximum 3 concurrent devices per account; a 4th login silently invalidates
> the oldest session.

This is also what production actually enforces (`DeviceRegistry`, `lemely/web`,
migration `0003_device_client_id`; see `reports/phase-1/REPORT.md` P1.11).
**Decision:** `PRODUCT.md` wins. No production change.

## Subject colour mapping

**Ledger id:** `brand-subject-color-mapping-mismatch`

The canvas assigned subject colours differently from the shipped mapping.
DESIGN.md §3.8 is authoritative and fixed:

| Subject | Pastel |
|---|---|
| Mathematics | `--pastel-sky` |
| Physics | `--pastel-lilac` |
| Chemistry | `--pastel-sage` |
| Biology | `--pastel-clay` |
| English | `--pastel-amber` |
| Unassigned / other | `--pastel-rose` |

**Decision:** the canvas mapping is superseded. New subjects extend the §3.8
table first; a subject colour is never picked at a call site. No production
change.

## Instrument Serif

**Ledger id:** `x-type-instrument-serif-rejected`

The build-era system (and the canvas that explored it) used Instrument Serif
as the display face. It is rejected: DESIGN.md §4 explains why (a single 400
weight with no bold forces every heading hierarchy to be built from size
alone, which is exactly what produced the build-era teacher portal's six
ad-hoc heading sizes across eighteen screens). The four faces the product
actually uses are:

| Role | Face |
|---|---|
| Display | Newsreader Variable |
| UI / body | Geist Variable |
| Data | JetBrains Mono Variable |
| Marginalia | Caveat Variable |

**Decision:** Instrument Serif stays rejected. No production change.

## "Academic Warmth" colour system

**Ledger id:** `brand-color-system-superseded`

The build-era system's name for its Material-3-derived palette (terracotta
`#964232` / teal `#006857` on `#fff8f6`; see `BUILD/DESIGN-AUDIT.md`) is
superseded by DESIGN.md §3's OKLCH colour ladder. **Decision:** "Academic
Warmth" is retired; §3 is the only colour system in force. No production
change.

## Hero grade on the student home

**Ledger id:** `student-home-no-hero-grade`

The canvas's student home showed one large "hero" grade at the top of the
page. Production does not build this: the student Overview reports
per-subject predicted grades, and a single cross-subject hero grade would be
an aggregate the product does not compute (there is no defined way to combine
a Mathematics predicted grade and a Chemistry predicted grade into one
number, and inventing one would be exactly the kind of fabricated headline
statistic `brand-cover-headline-and-stats-fabricated` already flags
elsewhere in this dossier). **Decision:** not built, by design. No production
change.

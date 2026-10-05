"""The unit and function-name tables behind :mod:`lemely.core.equivalence` (#271).

Pure data, split out of the facade so the parse worker's child process can
import the tables without importing the normalisation passes. Imports only
``re``, ``sympy`` and SymPy's parser transformations; nothing here depends on
:mod:`lemely.core.equivalence` or :mod:`lemely.core.equivalence_worker`.
"""

from __future__ import annotations

import re

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    standard_transformations,
)

_TRANSFORMATIONS = (
    *standard_transformations,
    implicit_multiplication_application,
    convert_xor,
)

#: The two code points for "micro". U+00B5 (the MICRO SIGN a keyboard or
#: a PDF often gives) is folded to U+03BC (GREEK SMALL LETTER MU) before
#: anything else runs, so the unit tables and the letter class hold one
#: spelling (#270). Python's tokenizer NFKC-folds an identifier's U+00B5
#: to U+03BC, so a ``local_dict`` key spelled with U+00B5 is never the
#: name SymPy looks up: ``4.5 \u00b5g`` was a NameError (unparseable) while
#: ``4.5 \u03bcg``, never protected, split into ``4.5*g*\u03bc``.
_MICRO_SIGN = "\u00b5"
_GREEK_MU = "\u03bc"

#: Base SI/CAIE unit symbols. Ordered longest-first so the unit-digit
#: alternation below cannot match a short prefix of a longer symbol (e.g.
#: "cm" before "c").
_BASE_UNIT_SYMBOLS = (
    "mol",
    "atm",
    "cm",
    "mm",
    "km",
    "kg",
    "Hz",
    "Pa",
    "cd",
    "m",
    "g",
    "s",
    "N",
    "J",
    "W",
    "A",
    "V",
    "C",
    "F",
    "T",
    "H",
    "K",
    "L",
    "l",
    "Ω",
)

#: SI prefixes CAIE mark schemes combine with a base unit ("mg", "kJ",
#: "MHz", ...). Each (prefix, base) pair is protected as its OWN atomic
#: symbol — never as prefix-symbol times base-symbol — because "mg" is a
#: unit of mass, not the product of a unit "m" (metre) and a unit "g"
#: (gram). Without this, "4.5 mg" and "4.5 gm" (gram times metre, a
#: dimensionally different and nonsensical quantity here) parse to the same
#: expression and compare `equal` (I8 review mechanism 5).
#:
#: KNOWN LIMITATION (I8 re-review round 4 SHOULD-FIX 7, deliberately not
#: fixed): "m" is the one SI prefix that is ALSO a base unit symbol
#: (metre), so a compound written with no separator and no exponent on the
#: first factor is genuinely ambiguous — "kg ms^-2" reads as
#: `kg / ms**2` (kilogram per millisecond squared, the atomic-prefix
#: reading this table exists for) rather than `kg * m / s**2` (the newton,
#: what "kg m s^-2" without the missing space meant). Every discriminator
#: tried (neighbouring-token context, exponent position, a
#: prefix-plus-exponent rule) either breaks a case this table is already
#: pinned on (`g/cm3`, `4.5 mg`) or trades this known over-rejection for a
#: new silent WRONG parse on the award path — worse, since a wrong parse
#: can auto-award and an over-rejection can only route to review. The only
#: correct discriminator is a dimensional-plausibility check against a
#: table of named derived units, which is a different, larger piece of
#: work than this module. The affected shape is narrow — a two-letter
#: prefix-ambiguous factor (`mA`, `mC`, `mF`, `mg`, `mH`, `mJ`, `mK`, `mL`,
#: `ml`, `mm`, `mN`, `ms`, `mT`, `mV`, `mW`), no separator, no exponent on
#: that factor specifically — and the direction is always over-rejection
#: (`not_equal`, never a false `equal_proven`): pinned by
#: ``test_kg_ms_known_limitation_is_not_equal_never_equal_proven`` in
#: tests/test_equivalence.py.
#:
#: Micro is spelled U+03BC (:data:`_GREEK_MU`; :func:`_normalize_text` folds
#: the micro sign to it first); ``u`` stays as its ASCII alias.
_SI_PREFIXES = ("p", "n", _GREEK_MU, "u", "m", "c", "d", "k", "M", "G")

_UNIT_SYMBOLS: tuple[str, ...] = _BASE_UNIT_SYMBOLS + tuple(
    prefix + base for prefix in _SI_PREFIXES for base in _BASE_UNIT_SYMBOLS
)
_SINGLE_LETTER_UNITS = frozenset(unit for unit in _UNIT_SYMBOLS if len(unit) == 1)

#: The letters a subscript can follow: Latin, the degree sign the unit
#: tables use, and Greek -- capitals U+0391-U+03A9 (Ω, U+03A9, is also the
#: ohm), lower case U+03B1-U+03C9 (final sigma ς included; micro, U+03BC,
#: is in this range once :func:`_normalize_text` has folded the micro sign,
#: #270), and the variant forms a transcriber or keyboard produces for the same letters
#: (ϑ U+03D1, ϕ U+03D5, ϖ U+03D6, ϰ U+03F0, ϱ U+03F1, ϵ U+03F5). Review
#: round 3: without Greek, SymPy still split `ε0` into `ε*0` = 0, `θ1+θ2`
#: into `3θ` and `μ0*I` into 0 -- each a false EQUAL_PROVEN. This module
#: does not normalise the Unicode subscript digits of a handwritten `ε₀`
#: (it is unparseable, so it routes to review); a transcriber's `ε0` is the
#: form that reaches this rule.
_SUBSCRIPTABLE_LETTERS = "A-Za-zΩ°\u0391-\u03a9\u03b1-\u03c9\u03d1\u03d5\u03d6\u03f0\u03f1\u03f5"

#: A run of letters directly followed by digits (`cm3`, `m2`, `N0`, `x2`,
#: `v1`, `mv2`, `ε0`), not itself preceded by a letter or `_`. A digit MAY
#: precede it (`4x2`, `30cm3`); scientific notation (`3e8`) is excluded in
#: `_rewrite_digit_suffixes`.
_LETTER_DIGITS_RE = re.compile(
    rf"(?<![{_SUBSCRIPTABLE_LETTERS}_])([{_SUBSCRIPTABLE_LETTERS}]+)(\d+)(?![\d.])"
)

#: Unit spellings that are textually different but dimensionally identical,
#: normalised to a single canonical spelling before parsing so e.g. "g/cm3"
#: and "g cm^-3" are compared as the same symbolic expression rather than
#: relying on `simplify` to discover the identity from scratch.
_UNIT_ALIASES: dict[str, str] = {
    "ohm": "Ω",
    "degC": "°C",
    "degreeC": "°C",
}

#: Names SymPy's default global namespace already binds to something other
#: than a free variable, but which are exactly the symbols CAIE physics
#: questions use most (energy `E`, current/imaginary `I`). Left unprotected,
#: `"E"` parses as `sympy.E` (Euler's number) and `"I"` as the imaginary
#: unit, so e.g. `equivalent("E", "2.718281828459045")` was reported `equal`
#: — a wrong physics answer confirmed by an unrelated mathematical identity
#: (I8 review mechanism 4). Shadowing them as plain symbols here means a
#: literal `E`/`I`/etc. typed in student or mark-scheme text is always
#: treated as the variable it is meant to be, never as the SymPy constant.
_RESERVED_NAME_OVERRIDES = ("E", "I", "O", "S", "Q", "oo", "zoo", "nan")

#: Predefined as ``local_dict`` when parsing, for two reasons:
#: (1) SymPy's `split_symbols` (part of `implicit_multiplication_application`)
#: otherwise splits multi-letter identifiers into single-letter factors —
#: without this, "cm" parses as `c * m` and "mg" as `m * g`.
#: (2) a handful of names collide with SymPy's default global namespace
#: (`_RESERVED_NAME_OVERRIDES` above).
#: Every unit symbol is included regardless of length (I8 review fix #4) —
#: a bare single-letter unit needs no *splitting* protection, but including
#: it here is harmless and keeps this the one place unit identity is
#: defined.
_UNIT_LOCAL_DICT: dict[str, sympy.Symbol] = {
    symbol: sympy.Symbol(symbol) for symbol in (*_UNIT_SYMBOLS, *_RESERVED_NAME_OVERRIDES)
}

#: Function calls this module will evaluate. Anything else that IS a known
#: SymPy callable — `factorial(100000)`, `Integral(...)` — is rejected
#: outright rather than handed to SymPy: both can be made arbitrarily
#: expensive, and `Integral` in particular reaches SymPy machinery with no
#: relevance to mark-scheme text (I8 review, "silent WRONG parses" table).
#: This is an allowlist among SymPy's own names, not a blocklist on
#: identifiers generally — an identifier that is NOT a SymPy attribute
#: (`a`, `x`, `v`, `T`, ...) is never treated as a "call" here regardless
#: of what follows it: implicit multiplication turns `a(b+c)`/`x(x+1)`/
#: `v(t)` into ordinary products, which is what a student meant. Checking
#: `hasattr(sympy, name)` is what makes that distinction — the earlier
#: version rejected identifier-before-`(` unconditionally and took out
#: every such row (I8 review S1).
_ALLOWED_FUNCTIONS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "sqrt",
        "log",
        "ln",
        "exp",
        "Abs",
    }
)
_FUNCTION_CALL_RE = re.compile(r"([A-Za-zΩ°][A-Za-z0-9]*)\s*\(")


def _is_disallowed_sympy_call(name: str) -> bool:
    return name not in _ALLOWED_FUNCTIONS and hasattr(sympy, name)

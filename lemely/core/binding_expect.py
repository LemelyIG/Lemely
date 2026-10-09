"""Expected answer shape and expected numeric values of a mark scheme leaf.

Detection only, never to award marks. The shift detector uses these to ask
whether a student's answer looks like the value expected of the *neighbouring*
question and not of its own. Because a false "matches" is the costly error,
every reader here returns nothing when it cannot read a value with confidence.
"""

from __future__ import annotations

import re
from typing import Literal

from lemely.core.loose_schemas import AnswerPoint, MathMarkType, Question

Shape = Literal["number", "text", "drawing", "unknown"]

_RELATIVE_TOLERANCE = 0.02
_MAX_EXPONENT = 40

_MINUS = "-\u2212"
_MULTIPLY = "[\u00d7x*]"

# ``1.8 x 10^5``, ``1.8 x 10⁵``, and ``1.8 x 105`` where PDF extraction lost the
# superscript so the exponent is glued to the ``10``.
_STANDARD_FORM = (
    rf"(?P<mant>\d+(?:\.\d+)?)\s*{_MULTIPLY}\s*10"
    rf"(?:\s*(?:\^|\*\*)\s*\(?(?P<exp_caret>[{_MINUS}\u2013]?\d+)\)?"
    rf"|(?P<exp_sup>[⁻⁰¹²³⁴-⁹]+)"
    rf"|(?P<exp_glued>[{_MINUS}\u2013]?\d+))"
)
_E_NOTATION = r"(?P<e_mant>\d+(?:\.\d+)?)[eE](?P<e_exp>[-+]?\d+)(?![\w.])"
# ``1,8`` / ``12,5`` may be a decimal comma, so it is consumed and yields nothing.
_PLAIN_NUMBER = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|\d+(?:\.\d+)?)"
_AMBIGUOUS_COMMA = r"(?P<amb>\d+,\d{1,2}(?!\d))"

_SUPERSCRIPT_DIGITS = str.maketrans("⁻⁰¹²³⁴⁵⁶⁷⁸⁹", "-0123456789")

_ALTERNATIVE_SPLIT = re.compile(r"\s+(?:OR|AND)\s+|\n")
_LEADING_STANDARD_FORM = re.compile(rf"^{_STANDARD_FORM}")
_LEADING_NUMBER = re.compile(
    rf"^(?P<sign>[{_MINUS}]?)"
    rf"(?P<num>\d{{1,3}}(?:[ ,]\d{{3}})+(?:\.\d+)?(?!\d)|\d+(?:\.\d+)?)(?:\(\d+\))?"
)
_PLAIN_DECIMAL = re.compile(r"^-?\d*\.\d+$")

_ANSWER_TOKEN = re.compile(
    rf"(?<![A-Za-z\d.^_])(?P<sign>(?<![\w.])[{_MINUS}](?=\d))?"
    rf"(?:{_STANDARD_FORM}|{_E_NOTATION}|{_AMBIGUOUS_COMMA}|{_PLAIN_NUMBER})"
)
_ENUMERATOR = re.compile(r"(?<![\w.])\d{1,2}[.)]\s+(?=[-\d])")
_WORD = re.compile(r"[A-Za-zµΩ°]+")
_DRAWING_WORDS = re.compile(r"\b(?:diagram|drawn|drawing|field\s+lines?)\b", re.IGNORECASE)

_UNITS = frozenset(
    """
    m cm mm km nm um µm dm s ms h hr min kg g mg n j kj mj w kw mw pa kpa mpa hz khz mhz
    v mv kv a ma ω Ω ohm ohms c k ° °c % mol rad deg degrees ev kev mev t f l ml
    year years day days hour hours minute minutes second seconds metre metres meter meters
    newton newtons joule joules watt watts volt volts amp amps kelvin cal
    """.split()  # noqa: SIM905 - a word list reads better than a list literal
)
_UNIT_STRIP = re.compile(r"[()\[\]\d^²³⁻\-\u2212\u2013+.,;:]")


_ANNOTATIONS = frozenset({"oe", "cao", "nfww", "www", "isw", "soi", "ft", "awrt", "aef"})


def _unit_tokens_ok(rest: str) -> bool:
    """True when ``rest`` is empty or only units and mark-scheme annotations.

    A comma, or a token with no letters (a second number or an operator after
    the value), means an expression or a list, so it is not a bare value.
    """
    if "," in rest:
        return False
    for chunk in re.split(r"[\s/\u00b7*]+", rest.strip()):
        token = _UNIT_STRIP.sub("", chunk).lower()
        if chunk and not re.search(r"[^\W\d_]|%|\u00b0", chunk):
            return False
        if token and token not in _UNITS and token not in _ANNOTATIONS:
            return False
    return True


def _exponent(match: re.Match[str]) -> int | None:
    group = match.groupdict()
    raw = group.get("exp_caret")
    glued = False
    if raw is None and group.get("exp_sup"):
        raw = group["exp_sup"].translate(_SUPERSCRIPT_DIGITS)
    if raw is None:
        raw = group.get("exp_glued")
        glued = True
    if raw is None:
        return None
    raw = raw.replace("\u2212", "-").replace("\u2013", "-")
    digits = raw.lstrip("-")
    # Bound the run before int(): a hostile digit run would hit Python's int limit.
    if len(digits) > 3:
        return None
    # ``2 x 1000`` is a product, not 2 x 10^0 with a lost superscript.
    if glued and digits.startswith("0"):
        return None
    exponent = int(raw)
    return exponent if abs(exponent) <= _MAX_EXPONENT else None


def _standard_form_value(match: re.Match[str]) -> str | None:
    exponent = _exponent(match)
    if exponent is None:
        return None
    return f"{match.group('mant')}e{exponent}"


def _leading_value(alternative: str) -> str | None:
    """The numeric value an alternative starts with, units stripped, else None."""
    text = alternative.strip()
    # Splitting on AND/OR can leave a stray half of a bracketed phrase.
    if text.count("(") != text.count(")"):
        return None
    standard = _LEADING_STANDARD_FORM.match(text)
    if standard:
        value = _standard_form_value(standard)
        if value is None or not _unit_tokens_ok(text[standard.end() :]):
            return None
        return value
    number = _LEADING_NUMBER.match(text)
    if not number:
        return None
    rest = text[number.end() :]
    if rest[:1].isdigit() or not _unit_tokens_ok(rest):
        return None
    digits = number.group("num").replace(",", "").replace(" ", "")
    return ("-" if number.group("sign") else "") + digits


def _format_float(value: float) -> str:
    text = repr(value)
    return text[:-2] if text.endswith(".0") else text


_OR_SPLIT = re.compile(r"\s+OR\s+")


def _untyped_values(point: AnswerPoint) -> list[str]:
    """Values of an untyped point, only where an alternative is a single bare value."""
    values: list[str] = []
    for alternative in _OR_SPLIT.split(point.point):
        if "\n" in alternative or re.search(r"\bAND\b", alternative):
            continue
        value = _leading_value(alternative)
        if value is not None:
            values.append(value)
    return values


def _point_values(point: AnswerPoint) -> list[str]:
    if point.math_mark_type is None:
        return _untyped_values(point)
    if point.math_mark_type not in (MathMarkType.A, MathMarkType.B):
        return []
    calculated = point.calculated_answer
    if calculated is not None and calculated.value is not None:
        return [_format_float(calculated.value)]
    values: list[str] = []
    for alternative in _ALTERNATIVE_SPLIT.split(point.point):
        value = _leading_value(alternative)
        if value is not None:
            values.append(value)
    return values


def expected_numeric_values(question: Question) -> list[str]:
    """Final-answer values of the leaf, units stripped; ``[]`` when it has none.

    Points typed A or B contribute their leading value; C and M (method) points
    never do; untyped points contribute only when an OR-alternative is a single
    bare value (number, optional unit, optional annotation such as ``oe``).
    When in doubt nothing is contributed: a false value is worse than a missing one.
    """
    values: list[str] = []
    for point in question.answer_points:
        for value in _point_values(point):
            if value not in values:
                values.append(value)
    return values


def _is_prose(point: AnswerPoint) -> bool:
    if "=" in point.point:
        return False
    alternatives = _ALTERNATIVE_SPLIT.split(point.point)
    if any(re.match(r"^\s*[-\u2212]?\d", alternative) for alternative in alternatives):
        return False
    return any(len(word) >= 3 for word in _WORD.findall(point.point))


def expected_shape(question: Question) -> Shape:
    """What kind of answer the leaf expects."""
    if question.drawing_criteria or question.plot_requirements:
        return "drawing"
    if expected_numeric_values(question):
        return "number"
    points = question.answer_points
    if points and all(_is_prose(point) for point in points):
        return "text"
    return "unknown"


def _is_unit_word(word: str) -> bool:
    # A lone lowercase ``a`` is far likelier a label (``3a``) than amperes.
    return word.lower() in _UNITS and word != "a"


def _answer_values(answer: str) -> list[str]:
    """Every numeric value in an answer text, as float-parsable strings."""
    text = _ENUMERATOR.sub("", answer)
    values: list[str] = []
    for match in _ANSWER_TOKEN.finditer(text):
        if match.group("amb") is not None:
            continue
        glued = _WORD.match(text, match.end())
        if glued and not _is_unit_word(glued.group()):
            continue
        if match.group("mant") is not None:
            value = _standard_form_value(match)
        elif match.group("e_mant") is not None:
            value = f"{match.group('e_mant')}e{match.group('e_exp')}"
        else:
            value = match.group("num").replace(",", "")
        if value is None:
            continue
        if match.group("sign"):
            value = "-" + value
        values.append(value)
    return values


def answer_shape(answer: str) -> Shape:
    """What kind of answer the text is: a value, a drawing, or prose."""
    text = answer.strip()
    if text.startswith("[") or _DRAWING_WORDS.search(text):
        return "drawing"
    if not _answer_values(text):
        return "text"
    remainder = _ANSWER_TOKEN.sub(" ", _ENUMERATOR.sub("", text))
    other_words = [word for word in _WORD.findall(remainder) if word.lower() not in _UNITS]
    return "number" if len(other_words) <= 3 else "text"


def _values_match(answer_value: str, expected_value: str) -> bool:
    try:
        got, want = float(answer_value), float(expected_value)
    except ValueError:
        return False
    if got == want:
        return True
    # Rounding slack is only granted to plain decimals; an integer or a
    # standard-form value needs an exact match (422.5 is not 420).
    if _PLAIN_DECIMAL.match(expected_value) and want != 0:
        return abs(got - want) <= _RELATIVE_TOLERANCE * abs(want)
    return False


def matches_expected(answer: str, question: Question) -> bool:
    """True when ``answer`` holds a value equal to an expected final-answer value.

    A plain-decimal expected value (``0.28``) also accepts a 2% relative
    difference; integers and standard-form values must match exactly.

    Both sides are plain numerics, so float comparison decides every pair and
    ``lemely.core.equivalence.equivalent`` is never needed. A pair that cannot
    be read counts as no match.
    """
    expected = expected_numeric_values(question)
    if not expected or answer_shape(answer) != "number":
        return False
    return any(_values_match(got, want) for got in _answer_values(answer) for want in expected)

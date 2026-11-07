"""The widened vocabulary table: functions, properties and typed binding.

Every positive is checked in ja/en/zh, every row has a negative corpus (each entry is a miss and
says why), and a leftover word turns any function x property pair into a miss.  Widening is data:
the monomial row and the minus-sign affine rows are deliberately absent from the packaged table
and are added here by table extension.
"""

from __future__ import annotations

import copy
import itertools
import re

import pytest

from pals_agent.recipe_instantiation import elaborate
from pals_agent.request_proposition import (
    _Grammar,
    bind_recipe,
    build_grammar,
    deterministic_instance_proposal,
    parse_request,
)
from tests.unit.test_request_proposition import _payload

FUNCTION_IDS = ("power", "exp", "sin", "cos", "abs", "sqrt", "scaled", "affine")
PROPERTY_IDS = (
    "uniformly_continuous", "continuous", "differentiable", "strictly_increasing", "monotone",
    "injective",
)
LEAN_PROPERTY = {
    "continuous": "Continuous (fun x : ℝ => {})",
    "uniformly_continuous": "UniformContinuous (fun x : ℝ => {})",
    "differentiable": "Differentiable ℝ (fun x : ℝ => {})",
    "strictly_increasing": "StrictMono (fun x : ℝ => {})",
    "monotone": "Monotone (fun x : ℝ => {})",
    "injective": "Function.Injective (fun x : ℝ => {})",
}
# Property wording per language: (ja, en, zh).
PROPERTY_WORDS = {
    "continuous": ("連続", "continuous", "连续"),
    "uniformly_continuous": ("一様連続", "uniformly continuous", "一致连续"),
    "differentiable": ("微分可能", "differentiable", "可导"),
    "strictly_increasing": ("狭義単調増加", "strictly increasing", "严格单调递增"),
    "monotone": ("広義単調増加", "nondecreasing", "单调不减"),
    "injective": ("単射", "injective", "单射"),
}
SENTENCE = (
    "{f} は{p}であることを示せ",
    "Prove that {f} is {p}.",
    "证明 {f} {p}",
)

# (function id, fragment as typed, Lean body); the fragments of every wording the table lists.
FRAGMENTS = [
    ("power", "x^2", "x ^ 2"), ("power", "x²", "x ^ 2"), ("power", "xの3乗", "x ^ 3"),
    ("power", "x**4", "x ^ 4"), ("power", "x raised to the 5th power", "x ^ 5"),
    ("power", "x的立方", "x ^ 3"),
    ("exp", "e^x", "Real.exp x"), ("exp", "e^{x}", "Real.exp x"), ("exp", "e^(x)", "Real.exp x"),
    ("exp", "exp(x)", "Real.exp x"), ("exp", "exp x", "Real.exp x"), ("exp", "expx", "Real.exp x"),
    ("exp", "eˣ", "Real.exp x"), ("exp", "ｅ^ｘ", "Real.exp x"),
    ("exp", "\\exp(t)", "Real.exp t"), ("exp", "e ^ y", "Real.exp y"),
    ("sin", "sin x", "Real.sin x"), ("sin", "sin(x)", "Real.sin x"), ("sin", "sinx", "Real.sin x"),
    ("sin", "sine of x", "Real.sin x"), ("sin", "xの正弦", "Real.sin x"),
    ("sin", "x的正弦", "Real.sin x"), ("sin", "\\sin(t)", "Real.sin t"),
    ("cos", "cos x", "Real.cos x"), ("cos", "cos(x)", "Real.cos x"), ("cos", "cosx", "Real.cos x"),
    ("cos", "cosine of x", "Real.cos x"), ("cos", "xの余弦", "Real.cos x"),
    ("cos", "x的余弦", "Real.cos x"),
    ("abs", "|x|", "|x|"), ("abs", "｜x｜", "|x|"), ("abs", "abs(x)", "|x|"),
    ("abs", "abs x", "|x|"), ("abs", "absolute value of x", "|x|"),
    ("abs", "xの絶対値", "|x|"), ("abs", "x的绝对值", "|x|"), ("abs", "|t|", "|t|"),
    ("sqrt", "√x", "Real.sqrt x"), ("sqrt", "√(x)", "Real.sqrt x"),
    ("sqrt", "sqrt(x)", "Real.sqrt x"), ("sqrt", "sqrt x", "Real.sqrt x"),
    ("sqrt", "square root of x", "Real.sqrt x"), ("sqrt", "xの平方根", "Real.sqrt x"),
    ("sqrt", "x的平方根", "Real.sqrt x"), ("sqrt", "ルートx", "Real.sqrt x"),
    ("sqrt", "\\sqrt{x}", "Real.sqrt x"),
    ("scaled", "3x", "3 * x"), ("scaled", "3*x", "3 * x"), ("scaled", "7·x", "7 * x"),
    ("scaled", "2 × x", "2 * x"), ("scaled", "5 times x", "5 * x"), ("scaled", "xの2倍", "2 * x"),
    ("scaled", "0.5x", "0.5 * x"), ("scaled", "2.25*t", "2.25 * t"),
    ("scaled", "123456789x", "123456789 * x"), ("scaled", "1.123456x", "1.123456 * x"),
    ("affine", "2x+1", "2 * x + 1"), ("affine", "2x + 1", "2 * x + 1"),
    ("affine", "1.5x + 2.5", "1.5 * x + 2.5"), ("affine", "x + 2", "x + 2"),
    ("affine", "3 + 2x", "3 + 2 * x"), ("affine", "4 + x", "4 + x"),
    ("affine", "2*x + 0.5", "2 * x + 0.5"), ("affine", "y+3", "y + 3"),
]


def _expected(prop: str, body: str) -> str:
    return LEAN_PROPERTY[prop].format(body).replace("fun x :", f"fun {_binder(body)} :")


def _binder(body: str) -> str:
    # The bound variable is the letter of the fragment, not always x.
    match = re.search(r"(?<![\w.])([stuvwxy])(?![\w.])", body)
    return match.group(1) if match else "x"


def _replace_variable(prop_text: str, body: str) -> str:
    name = _binder(body)
    return prop_text.replace("fun x :", f"fun {name} :") if name != "x" else prop_text


@pytest.mark.parametrize(
    ("function_id", "fragment", "body"), FRAGMENTS, ids=[f[1] for f in FRAGMENTS]
)
def test_every_wording_parses_with_every_property_in_three_languages(
    function_id: str, fragment: str, body: str
) -> None:
    for prop, words in PROPERTY_WORDS.items():
        for sentence, word in zip(SENTENCE, words, strict=True):
            text = sentence.format(f=fragment, p=word)
            parsed = parse_request(text)
            assert parsed is not None, text
            assert parsed.function_id == function_id, text
            assert parsed.property_id == prop, text
            assert parsed.proposition == _replace_variable(
                LEAN_PROPERTY[prop].format(body), body
            ), text


@pytest.mark.parametrize(
    ("text", "function_id", "property_id"),
    [
        ("Is 7·x uniformly continuous?", "scaled", "uniformly_continuous"),
        ("sin x の連続性", "sin", "continuous"),
        ("|x| の微分可能性", "abs", "differentiable"),
        ("e^x is strictly monotone increasing", "exp", "strictly_increasing"),
        ("x^3 is nondecreasing", "power", "monotone"),
        ("x^3 is weakly increasing", "power", "monotone"),
        ("x^3 is non-decreasing", "power", "monotone"),
        ("x^3 は単調非減少", "power", "monotone"),
        ("x^3 は狭義単調増加", "power", "strictly_increasing"),
        ("x^3 is one-to-one is not a property here: injection", "power", "injective"),
    ][:-1],
)
def test_assorted_sentences(text: str, function_id: str, property_id: str) -> None:
    parsed = parse_request(text)
    assert parsed is not None
    assert (parsed.function_id, parsed.property_id) == (function_id, property_id)


def test_uniform_continuity_is_never_read_as_plain_continuity() -> None:
    for text in ("x^2 は一様連続", "x^2 is uniformly continuous", "证明 x^2 一致连续",
                 "uniform continuity of x^2"):
        parsed = parse_request(text)
        assert parsed is not None and parsed.property_id == "uniformly_continuous", text
        assert parsed.proposition.startswith("UniformContinuous")
    both = parse_request("x^2 は一様連続かつ連続")
    assert both is None  # two properties


def test_the_search_query_carries_function_and_property_words() -> None:
    parsed = parse_request("sin x is differentiable")
    assert parsed is not None
    assert "sine" in parsed.search_query and "differentiable" in parsed.search_query
    parsed = parse_request("x^3 is injective")
    assert parsed is not None and "injective" in parsed.search_query
    uniform = parse_request("x^3 is uniformly continuous")
    assert uniform is not None and uniform.preferred_method == "epsilon_delta"
    strict = parse_request("x^3 is strictly increasing")
    assert strict is not None and strict.preferred_method is None


# --- negatives: every entry is a miss, with its reason ------------------------------------------

NEGATIVES = [
    # power (existing row, new hazards)
    ("e^2 は連続", "e is Euler's constant, not a real variable"),
    ("X^2 is continuous", "a capital letter is a set or a random variable"),
    ("n^2 is continuous", "n is conventionally a natural number"),
    ("k^3 は連続", "k is conventionally an integer"),
    ("z^2 is continuous", "z is conventionally complex"),
    ("x^2! is continuous", "a factorial mark changes the term"),
    ("(x^2)' is continuous", "a prime is the derivative"),
    ("the square function is continuous", "'square function' also names other objects"),
    ("x**2.5 is continuous", "a fractional exponent"),
    # exp
    ("e^(-x) is continuous", "negative argument is a composition"),
    ("e^{-x} is continuous", "negative argument is a composition"),
    ("e^{2x} is continuous", "scaled argument is a composition"),
    ("e^2x is continuous", "e^2 times x, or e^(2x): ambiguous"),
    ("e^x2 is continuous", "x2 is not x"),
    ("exp(x+1) is continuous", "shifted argument is a composition"),
    ("exp(-x) is continuous", "negative argument is a composition"),
    ("e^x^2 is continuous", "e^(x^2) or (e^x)^2"),
    ("e^(x^2) is continuous", "composition with a power"),
    ("e^x² is continuous", "e^(x^2) or (e^x)^2"),
    ("exp(x)^2 is continuous", "a power of the function"),
    ("2e^x is continuous", "an extra factor"),
    ("e^x + 1 is continuous", "a sum of terms"),
    ("x e^x is continuous", "a product"),
    ("2^x is continuous", "another base"),
    ("a^x is continuous", "another base"),
    ("exp(sin x) is continuous", "composition"),
    ("exp is continuous", "an unapplied function"),
    ("the exponential function is continuous", "may be a^x"),
    ("指数関数は連続", "may be a^x"),
    ("exp x² is continuous", "exp(x^2) or (exp x)^2"),
    # sin
    ("sin x^2 is continuous", "sin(x^2) or (sin x)^2"),
    ("sin x² is continuous", "sin(x^2) or (sin x)^2"),
    ("sin²x is continuous", "a squared sine"),
    ("sin^2 x is continuous", "a squared sine"),
    ("sin(x)^2 is continuous", "a squared sine"),
    ("sin(2x) is continuous", "scaled argument is a composition"),
    ("sin 2x is continuous", "sin(2x) or (sin 2)x"),
    ("sin(x+1) is continuous", "composition"),
    ("sin(-x) is continuous", "composition"),
    ("sinh x is continuous", "hyperbolic sine, not sine"),
    ("arcsin x is continuous", "inverse sine"),
    ("asin(x) is continuous", "inverse sine"),
    ("sinc x is continuous", "the sinc function"),
    ("sin(x)cos(x) is continuous", "a product"),
    ("sin x + 1 is continuous", "a sum of terms"),
    ("sin x / x is continuous", "a quotient"),
    ("2 sin x is continuous", "an extra factor"),
    ("sin(sin x) is continuous", "composition"),
    ("sin(x)! is continuous", "a factorial"),
    ("sin⁻¹ x is continuous", "inverse sine"),
    ("sin a is continuous", "'a' is the article, not a variable here"),
    ("sin is continuous", "an unapplied function"),
    ("the sine function is continuous", "no argument: a name only"),
    ("x sin x is continuous", "a product"),
    ("sin x cos x is continuous", "a product"),
    # cos
    ("cos x^2 is continuous", "cos(x^2) or (cos x)^2"),
    ("cos(x)^2 is continuous", "a squared cosine"),
    ("cosh x is continuous", "hyperbolic cosine"),
    ("arccos x is continuous", "inverse cosine"),
    ("cost function is continuous", "the word cost, not cos t"),
    ("cos(2x) is continuous", "composition"),
    ("cos x + sin x is continuous", "a sum of terms"),
    ("1 - cos x is continuous", "a sum of terms"),
    ("cos x sin x is continuous", "two functions"),
    ("余弦定理は連続", "the law of cosines"),
    # abs
    ("|x|^2 is continuous", "a power of the absolute value"),
    ("|x+1| is continuous", "a shifted argument"),
    ("|x-1| is continuous", "a shifted argument"),
    ("|2x| is continuous", "a scaled argument"),
    ("||x|| is continuous", "nested bars"),
    ("|x| + 1 is continuous", "a sum of terms"),
    ("|x||y| is continuous", "another variable"),
    ("abs(x)^2 is continuous", "a power of the absolute value"),
    ("abs(x - 1) is continuous", "a shifted argument"),
    ("abs is continuous", "an unapplied function"),
    ("the absolute value function is continuous", "no argument: a name only"),
    ("xの絶対値の2乗は連続", "a power of the absolute value"),
    ("absolute value of x squared is continuous", "(|x|)^2 or |x^2|"),
    ("|x| is absolutely continuous", "another property"),
    # sqrt
    ("√x² is continuous", "sqrt(x^2) or (sqrt x)^2"),
    ("√(x+1) is continuous", "a shifted argument"),
    ("sqrt(x^2) is continuous", "composition with a power"),
    ("sqrt(x)^3 is continuous", "a power of the root"),
    ("√x+1 is continuous", "a sum of terms"),
    ("2√x is continuous", "an extra factor"),
    ("sqrt 2x is continuous", "sqrt(2x) or (sqrt 2)x"),
    ("√(√x) is continuous", "composition"),
    ("x^(1/2) is continuous", "a fractional exponent"),
    ("cube root of x is continuous", "a different root"),
    ("立方根は連続", "a different root"),
    ("sqrt is continuous", "an unapplied function"),
    ("the square root function is continuous", "no argument: a name only"),
    ("x^2の平方根は連続", "a root of a power"),
    # scaled c x
    ("-3x is continuous", "a negative coefficient"),
    ("3 x is continuous", "a space between coefficient and variable is ambiguous"),
    ("x/2 is continuous", "a quotient"),
    ("(1/2)x is continuous", "a rational coefficient"),
    ("1/2 x is continuous", "a rational coefficient"),
    ("3x^2 is continuous", "a coefficient with a power: left to the model route"),
    ("3(x+1) is continuous", "an extra factor"),
    ("3xy is continuous", "another variable"),
    ("2D function is continuous", "a dimension, not 2d"),
    ("3rd is continuous", "an ordinal"),
    ("0x is injective", "a zero coefficient"),
    ("0.0x is injective", "a zero coefficient"),
    ("00x is continuous", "a leading zero"),
    ("03x is continuous", "a leading zero"),
    ("1,5x is continuous", "a decimal comma"),
    (".5x is continuous", "a decimal without integer part"),
    ("3.x is continuous", "a dangling point"),
    ("3xx is continuous", "another variable"),
    ("3x! is continuous", "a factorial"),
    ("x*3 is continuous", "the coefficient must come first"),
    ("1234567890x is continuous", "ten digits exceed the literal bound"),
    ("1.1234567x is continuous", "seven decimals exceed the literal bound"),
    ("3z is continuous", "z is conventionally complex"),
    ("3n is continuous", "n is conventionally a natural number"),
    # affine a x + b
    ("2x - 1 is injective", "a minus sign is left to the model route"),
    ("2x + y is continuous", "another variable"),
    ("2x + 1/2 is continuous", "a rational constant"),
    ("2x + 3^2 is continuous", "a power in the constant"),
    ("2x + x^2 is continuous", "a sum with a power"),
    ("2x + sin x is continuous", "a sum with another function"),
    ("1 + 2x + 3 is continuous", "three terms"),
    ("(2x+1)^2 is continuous", "a power of the affine map"),
    ("2(x+1) is continuous", "an extra factor"),
    ("x + 1 + 2 is continuous", "three terms"),
    ("2x+1.2.3 is continuous", "a malformed constant"),
    ("2x + 1,000 is continuous", "a thousands separator"),
    ("x + a is continuous", "a symbolic constant"),
    ("-x + 1 is continuous", "a negative coefficient"),
    ("2x+1=0 is continuous", "an equation"),
    ("0x + 1 is injective", "a zero coefficient"),
    ("2x + 1x is continuous", "a sum of two scaled terms"),
    ("x^2 + 1 is continuous", "a power plus a constant"),
    ("1 + x^2 is continuous", "a constant plus a power"),
    ("sin x + 1 is continuous", "a function plus a constant"),
    # properties
    ("x^2 is not continuous", "negation"),
    ("x^2 is discontinuous", "negation"),
    ("x^2 は不連続", "negation"),
    ("x^2 は連続でない", "negation"),
    ("x^2 is right continuous", "one-sided continuity"),
    ("x^2 は左連続", "one-sided continuity"),
    ("x^2 is absolutely continuous", "another property"),
    ("x^2 is piecewise continuous", "another property"),
    ("x^2 is continuously differentiable", "C^1, not differentiable"),
    ("x^2 は連続微分可能", "C^1, not differentiable"),
    ("x^2 is continuous and differentiable", "two properties"),
    ("x^2 is non-uniformly continuous", "negation"),
    ("x^2 is uniformly continuous on [0,1]", "restricted domain"),
    ("x^2 は一様連続でない", "negation"),
    ("x^2 is locally uniformly continuous", "another property"),
    ("x^2 is twice differentiable", "another property"),
    ("x^2 is differentiable at 0", "a point"),
    ("x^2 is nowhere differentiable", "negation"),
    ("x^2 is not differentiable", "negation"),
    ("x^2 は微分不可能", "negation"),
    ("x^2 は2回微分可能", "another property"),
    ("x^2 is increasing", "bare 'increasing' is strict or weak"),
    ("x^2 is monotone increasing", "strict or weak"),
    ("x^2 is monotonically increasing", "strict or weak"),
    ("x^2 は単調増加", "単調増加 is strict or weak"),
    ("x^2 是单调递增", "单调递增 is strict or weak"),
    ("x^2 is strictly decreasing", "another property"),
    ("x^2 is strictly monotone", "no direction"),
    ("x^2 は狭義単調減少", "another property"),
    ("x^2 is strictly increasing on [0,1]", "restricted domain"),
    ("x^2 is not strictly increasing", "negation"),
    ("x^2 is monotone", "no direction"),
    ("x^2 is nondecreasing on [0, ∞)", "restricted domain"),
    ("x^2 is non-increasing", "another property"),
    ("x^2 is weakly decreasing", "another property"),
    ("x^2 は単調非増加", "another property"),
    ("x^2 is surjective", "another property"),
    ("x^2 is bijective", "another property"),
    ("x^2 は全単射", "another property"),
    ("x^2 is one-to-one", "one-to-one is also used for a bijection"),
    ("x^2 is one-to-one correspondence", "a bijection"),
    ("x^2 は1対1", "1対1 is injective or bijective"),
    ("x^2 是一一对应", "a bijection"),
    ("x^2 is not injective", "negation"),
    ("x^2 is injective on [0,1]", "restricted domain"),
    ("x^2 は非単射", "negation"),
]


@pytest.mark.parametrize(
    ("text", "reason"), NEGATIVES, ids=[f"{i}-{reason}" for i, (_, reason) in enumerate(NEGATIVES)]
)
def test_the_negative_corpus_stays_a_miss(text: str, reason: str) -> None:
    assert parse_request(text) is None, (text, reason)


# --- a leftover word makes any function x property pair a miss ---------------------------------

LEFTOVER_WORDS = ("banana", "ちなみに", "however", "但是", "furthermore", "ほぼ", "and also")


def _one_fragment_per_function() -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for function_id, fragment, _ in FRAGMENTS:
        seen.setdefault(function_id, fragment)
    return list(seen.items())


@pytest.mark.parametrize("word", LEFTOVER_WORDS)
def test_any_leftover_word_turns_every_function_property_pair_into_a_miss(word: str) -> None:
    pairs = list(itertools.product(_one_fragment_per_function(), PROPERTY_WORDS.items()))
    assert len(pairs) == len(FUNCTION_IDS) * len(PROPERTY_IDS)
    for (function_id, fragment), (prop, words) in pairs:
        for sentence, phrase in zip(SENTENCE, words, strict=True):
            base = sentence.format(f=fragment, p=phrase)
            assert parse_request(base) is not None, base
            before, after = sentence.split("{f}")[0], sentence.split("{f}")[1]
            variants = [
                f"{word} {base}",
                f"{base} {word}",
                f"{before}{word} {fragment}{after.replace('{p}', phrase)}",
                f"{before}{fragment} {word}{after.replace('{p}', phrase)}",
                sentence.format(f=fragment, p=f"{word} {phrase}"),
                sentence.format(f=fragment, p=f"{phrase} {word}"),
            ]
            for variant in variants:
                assert parse_request(variant) is None, (function_id, prop, variant)


def test_every_function_and_property_row_of_the_table_is_covered_by_these_tests() -> None:
    grammar = build_grammar(_payload())
    assert tuple(f["id"] for f in grammar.functions) == FUNCTION_IDS
    assert tuple(p["id"] for p in grammar.properties) == PROPERTY_IDS


# --- table extension: the rows left out of the packaged table are data -------------------------

MONOMIAL_FORMS = [
    {"re": r"(?<![a-z0-9_.^/])(?P<c>(?!0(?:\.0+)?(?![0-9.]))(?:0|[1-9][0-9]{0,8})"
           r"(?:\.[0-9]{1,6})?)(?:\s*[*×·⋅]\s*|)(?P<v>[t-z])\s*\^\s*(?P<k>[0-9]{1,9})"
           r"(?![0-9]|\.[0-9]|\s*\^)"},
]


def _extended() -> _Grammar:
    payload = copy.deepcopy(_payload())
    payload["functions"].append({
        "id": "monomial", "lean_body": "{c} * {v} ^ {k}", "slots": {"c": "decimal", "k": "natural"},
        "search_terms": "monomial coefficient power", "forms": MONOMIAL_FORMS,
    })
    return build_grammar(payload)


def test_a_monomial_row_is_added_by_data_and_stays_unambiguous() -> None:
    grammar = _extended()
    cases = {
        "3x^2 is continuous": "Continuous (fun x : ℝ => 3 * x ^ 2)",
        "2.5*x^3 は連続": "Continuous (fun x : ℝ => 2.5 * x ^ 3)",
        "5x^4 is injective": "Function.Injective (fun x : ℝ => 5 * x ^ 4)",
        "2x³ is differentiable": "Differentiable ℝ (fun x : ℝ => 2 * x ^ 3)",
    }
    for text, expected in cases.items():
        parsed = parse_request(text, grammar=grammar)
        assert parsed is not None and parsed.proposition == expected, text
        assert parse_request(text) is None  # the packaged table does not know the row
    for text in ("3x^2 + 1 is continuous", "3x^2 y is continuous", "-3x^2 is continuous",
                 "3x^2^2 is continuous", "(3x)^2 is continuous", "3x^2.5 is continuous",
                 "0x^2 is continuous", "3x^-2 is continuous", "3e^x is continuous"):
        assert parse_request(text, grammar=grammar) is None, text
    # The bare power inside the monomial does not make it ambiguous: the longer reading wins.
    assert parse_request("x^2 is continuous", grammar=grammar) is not None


def test_a_minus_sign_affine_row_is_added_by_data() -> None:
    payload = copy.deepcopy(_payload())
    affine = next(f for f in payload["functions"] if f["id"] == "affine")
    affine["forms"].append({
        "re": r"(?<![a-z0-9_.^/])(?P<a>(?!0(?:\.0+)?(?![0-9.]))(?:0|[1-9][0-9]{0,8})"
              r"(?:\.[0-9]{1,6})?)(?P<v>[t-z])\s*[-−]\s*(?P<b>(?:0|[1-9][0-9]{0,8})"
              r"(?:\.[0-9]{1,6})?)(?![a-z0-9_^]|\.[0-9]|\s*\^)",
        "fixed": {"op": "-"},
    })
    grammar = build_grammar(payload)
    parsed = parse_request("2x - 1 is injective", grammar=grammar)
    assert parsed is not None
    assert parsed.proposition == "Function.Injective (fun x : ℝ => 2 * x - 1)"
    assert parse_request("2x - 1 is injective") is None


def test_overlapping_readings_of_two_functions_are_ambiguous() -> None:
    payload = copy.deepcopy(_payload())
    payload["functions"].append({
        "id": "clash", "lean_body": "Real.sin {v}", "slots": {}, "search_terms": "",
        "forms": [{"re": r"2\s+is(?![a-z])", "variable": "x"}],  # overlaps x^2 only partially
    })
    grammar = build_grammar(payload)
    assert parse_request("x^2 is continuous", grammar=grammar) is None


def test_a_function_name_beside_its_formula_must_agree_with_it() -> None:
    assert parse_request("二乗関数 f(x)=x^2 の連続性を証明せよ") is not None
    assert parse_request("二乗関数 f(x)=x^3 の連続性を証明せよ") is None  # the name says x^2
    assert parse_request("the fourth power function x⁴ is continuous") is not None
    assert parse_request("the fourth power function x^3 is continuous") is None
    assert parse_request("the sine function sin x is continuous") is not None
    assert parse_request("the sine function x^2 is continuous") is None
    assert parse_request("the exponential function e^x is continuous") is not None
    assert parse_request("the squaring function is continuous") is not None  # unambiguous alone
    assert parse_request("the sine function is continuous") is None  # a name alone is not enough


# --- typed binding -------------------------------------------------------------------------------

WIRE_LITERAL = re.compile(r"-?(?:0|[1-9][0-9]{0,8})\Z")


def _cont(body: str) -> str:
    return f"Continuous (fun x : ℝ => {body})"


@pytest.mark.parametrize("kind", ["ℝ", "ℚ", "ℤ", "ℕ", "Real", "Rat", "Int", "Nat"])
def test_every_numeric_kind_binds_an_integer_literal_as_a_hint(kind: str) -> None:
    target = f"∀ (c : {kind}), Continuous (fun x : ℝ => c * x)"
    assert bind_recipe(target, _cont("3 * x")) == (("c", "3"),)
    assert bind_recipe(target, _cont("0 * x")) == (("c", "0"),)
    assert bind_recipe(target, _cont("123456789 * x")) == (("c", "123456789"),)


@pytest.mark.parametrize("kind", ["ℝ", "ℚ", "Real", "Rat"])
def test_a_decimal_value_binds_without_a_hint(kind: str) -> None:
    target = f"∀ (c : {kind}), Continuous (fun x : ℝ => c * x)"
    assert bind_recipe(target, _cont("2.5 * x")) == ()
    assert bind_recipe(target, _cont("0.000001 * x")) == ()


@pytest.mark.parametrize("kind", ["ℤ", "ℕ", "Int", "Nat"])
def test_integer_and_natural_parameters_refuse_a_decimal(kind: str) -> None:
    target = f"∀ (c : {kind}), Continuous (fun x : ℝ => c * x)"
    assert bind_recipe(target, _cont("2.5 * x")) is None


def test_several_parameters_bind_together_and_decimals_drop_every_hint() -> None:
    target = "∀ (a b : ℝ), Continuous (fun x : ℝ => a * x + b)"
    assert bind_recipe(target, _cont("2 * x + 1")) == (("a", "2"), ("b", "1"))
    assert bind_recipe(target, _cont("2 * x + 0.5")) == ()  # no partial substitution
    assert bind_recipe(target, _cont("1.5 * x + 2")) == ()
    mixed = "∀ (n : ℕ) (c : ℝ), Continuous (fun x : ℝ => c * x ^ n)"
    assert bind_recipe(mixed, _cont("3 * x ^ 2")) == (("n", "2"), ("c", "3"))
    assert bind_recipe(mixed, _cont("2.5 * x ^ 3")) == ()
    assert bind_recipe(mixed, _cont("2.5 * x ^ 3.5")) is None  # the natural exponent is a literal


def test_a_non_natural_parameter_directly_after_a_caret_never_binds() -> None:
    for kind in ("ℝ", "ℚ", "ℤ"):
        assert bind_recipe(
            f"∀ (r : {kind}), Continuous (fun x : ℝ => x ^ r)", _cont("x ^ 2")
        ) is None
        assert bind_recipe(
            f"∀ (r : {kind}), Continuous (fun x : ℝ => x ^ (r))", _cont("x ^ (2)")
        ) is None
    assert bind_recipe(
        "∀ (c r : ℝ), Continuous (fun x : ℝ => c * x ^ r)", _cont("2 * x ^ 3")
    ) is None
    assert bind_recipe(
        "∀ (r : ℝ), Continuous (fun x : ℝ => x ^ r)", _cont("x ^ 2.5")
    ) is None
    # The same letter in a base position is not an exponent.
    assert bind_recipe(
        "∀ (r : ℝ), Continuous (fun x : ℝ => r ^ 2 * x)", _cont("3 ^ 2 * x")
    ) == (("r", "3"),)


def test_a_real_parameter_that_does_not_occur_or_repeats_keeps_its_old_behaviour() -> None:
    assert bind_recipe("∀ (c d : ℝ), Continuous (fun x : ℝ => c * x)", _cont("3 * x")) is None
    repeated = "∀ (c : ℝ), Continuous (fun x : ℝ => c * x + c)"
    assert bind_recipe(repeated, _cont("2 * x + 2")) == (("c", "2"),)
    assert bind_recipe(repeated, _cont("2 * x + 3")) is None
    assert bind_recipe(repeated, _cont("2.5 * x + 2.5")) == ()
    assert bind_recipe(repeated, _cont("2.5 * x + 2")) is None
    assert bind_recipe("∀ (f : ℝ → ℝ), Continuous f", _cont("3 * x")) is None
    assert bind_recipe("∀ (c : ℝ), Continuous (fun x : ℝ => c * x)", "not a statement") is None


def test_integer_hints_always_satisfy_the_wire_contract() -> None:
    target = "∀ (a b : ℝ), Continuous (fun x : ℝ => a * x + b)"
    for body in ("2 * x + 1", "0 * x + 0", "123456789 * x + 987654321"):
        bound = bind_recipe(target, _cont(body))
        assert bound is not None
        assert all(WIRE_LITERAL.fullmatch(value) for _, value in bound)


REAL_RECIPE = {
    "recipe_id": "scaled-continuity", "recipe_revision": 1,
    "target_source": "∀ (c : ℝ), Continuous (fun x : ℝ => c * x)",
    "proof_method_tag": None,
}


def test_the_deterministic_proposal_hints_integers_and_not_decimals() -> None:
    integer = deterministic_instance_proposal("3x の連続性を証明して", [REAL_RECIPE])
    assert integer is not None
    assert integer["bindings"] == [{"variable": "c", "value": "3"}]
    assert integer["requested_proposition"] == _cont("3 * x")
    decimal = deterministic_instance_proposal("Prove that 2.5x is continuous.", [REAL_RECIPE])
    assert decimal is not None
    assert decimal["bindings"] == []
    assert decimal["requested_proposition"] == _cont("2.5 * x")
    assert deterministic_instance_proposal("sin x の連続性", [REAL_RECIPE]) is None
    assert deterministic_instance_proposal("3x+1 の連続性", [REAL_RECIPE]) is None


def test_elaboration_gets_no_hint_for_a_decimal_and_lean_decides() -> None:
    source = "theorem scaled_cont (c : ℝ) : Continuous (fun x : ℝ => c * x) := by fun_prop\n"
    decimal = deterministic_instance_proposal("0.5x is continuous", [REAL_RECIPE])
    assert decimal is not None
    hints = [(item["variable"], item["value"]) for item in decimal["bindings"]]
    instance = elaborate(source, decimal["requested_proposition"], hints)
    assert instance.bindings == ()
    assert "(c :=" not in instance.source
    integer = deterministic_instance_proposal("3x is continuous", [REAL_RECIPE])
    assert integer is not None
    instance = elaborate(
        source, integer["requested_proposition"],
        [(item["variable"], item["value"]) for item in integer["bindings"]],
    )
    assert instance.bindings == (("c", "3"),)
    assert "exact scaled_cont (c := 3)" in instance.source

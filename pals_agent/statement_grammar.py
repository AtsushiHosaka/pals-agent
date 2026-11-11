"""One allow-list grammar for the propositions that reach Lean (every lane uses it).

A statement is untrusted text: a learner's request, or the output of a formalising model whose
prompt contained that request.  Lean elaboration can execute code (``by run_tac``, ``elab``,
``run_cmd``, macros, ``#eval``, ``IO`` actions, ``unsafe`` declarations), so a deny-list is not a
defence.  This module accepts a statement only if EVERY token is one of:

  * a numeral;
  * an identifier that is neither reserved (command, tactic-block and code-bearing words) nor in a
    code-bearing namespace (``IO``, ``Lean``, ``System``, ``Elab``, ``Meta``, ``unsafe*``,
    ``run_*``);
  * one of a fixed set of ASCII punctuation tokens, or a non-ASCII mathematical symbol or letter;
  * the keywords ``fun``, ``if``/``then``/``else`` and ``in``.

Everything else is refused: quotes and string/char literals, antiquotations, backticks, comments,
``:=``, ``;`` (except inside a ``!![ ... ]`` matrix literal), ``#``, ``@[``, ``<|``/``|>``,
newlines and control or format characters, ``by``, ``do``, ``let``, ``have``, ``show``, ``from``,
``set_option``, ``open``, ``unsafe``, ``elab``, ``macro``, ``syntax``, ``notation``, ``import`` and
all declaration keywords.  ``let`` is outside the grammar on purpose: it needs ``:=`` and ``;``.

This is the first of two layers.  The second is the sandbox the Lean process runs in (see
``sandbox``): a validator can miss a way for elaboration to execute code, a sandbox bounds what
that code can do.  Neither replaces the production verifier's isolation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from pals_agent.recipe_instantiation import InstantiationRejected

MAX_CHARS: Final = 4000
MAX_TOKENS: Final = 2500


class StatementRejected(InstantiationRejected):
    """The text is outside the proposition grammar."""


RESERVED: Final = frozenset(
    (
        "by",
        "do",
        "from",
        "show",
        "have",
        "let",
        "calc",
        "match",
        "with",
        "where",
        "at",
        "using",
        "only",
        "theorem",
        "lemma",
        "example",
        "def",
        "instance",
        "open",
        "namespace",
        "section",
        "end",
        "variable",
        "variables",
        "universe",
        "attribute",
        "macro",
        "macro_rules",
        "syntax",
        "notation",
        "elab",
        "elab_rules",
        "initialize",
        "builtin_initialize",
        "import",
        "deriving",
        "mutual",
        "partial",
        "private",
        "protected",
        "noncomputable",
        "unsafe",
        "opaque",
        "axiom",
        "constant",
        "abbrev",
        "structure",
        "class",
        "inductive",
        "extends",
        "local",
        "scoped",
        "set_option",
        "sorry",
        "admit",
        "run_cmd",
        "run_tac",
        "run_elab",
        "run_meta",
        "native_decide",
        "termination_by",
        "decreasing_by",
        "infix",
        "infixl",
        "infixr",
        "prefix",
        "postfix",
        "export",
        "include",
        "omit",
        "assume",
        "suffices",
        "obtain",
        "rcases",
        "rintro",
        "intro",
        "intros",
        "exact",
        "refine",
        "apply",
        "simp",
        "rw",
        "λ",
    )
)
ALLOWED_KEYWORDS: Final = frozenset({"fun", "if", "then", "else", "in"})
_CODE_NAMESPACES: Final = re.compile(r"^(IO|Lean|System|Elab|Meta|Tactic|Command|Std\.IO)(\.|$)")
_CODE_PREFIXES: Final = ("unsafe", "run_", "native_")
_ASCII_SYMBOLS: Final = frozenset("()[]{},:.|+-*/^=<>!%&~@")
_BANNED_SEQUENCES: Final = ("--", "/-", "-/", ":=", "@[", "<|", "|>")
_QUOTE_LIKE: Final = frozenset('«»‹›“”‘’„‟❝❞＂＇`$#"')
_OPEN: Final = {"(": ")", "[": "]", "{": "}", "⟨": "⟩", "⦃": "⦄", "⟪": "⟫", "⌊": "⌋", "⌈": "⌉"}
_CLOSE: Final = {v: k for k, v in _OPEN.items()}
_IDENT_START: Final = re.compile(r"[^\W\d]")
_IDENT: Final = re.compile(r"[^\W\d][\w'!?]*")
_NUMERAL: Final = re.compile(r"\d+(?:\.\d+)?")


def _refuse(why: str) -> StatementRejected:
    return StatementRejected(f"statement outside the proposition grammar: {why}")


def _ident_ok(name: str) -> None:
    parts = name.split(".")
    if _CODE_NAMESPACES.match(name):
        raise _refuse("code-bearing namespace")
    for part in parts:
        if part in RESERVED:
            raise _refuse(f"reserved word {part!r}")
        if part.startswith(_CODE_PREFIXES):
            raise _refuse("code-bearing identifier")
        if part in {"fun", "if", "then", "else", "in"} and len(parts) > 1:
            raise _refuse("keyword used as a name component")


def _char_class(ch: str) -> str:
    category = unicodedata.category(ch)
    if category[0] in "LNM" or ch == "_":
        return "word"
    if category[0] in "SP":
        return "symbol"
    if ch == " ":
        return "space"
    return "bad"


def validate_proposition(text: str) -> str:
    """The single-line proposition if every token is allowed; else raise StatementRejected."""
    if not isinstance(text, str):
        raise _refuse("not text")
    for ch in text:
        if ch in "\n\r\t":
            continue  # whitespace is normalised below (a newline can only separate tokens)
        if unicodedata.category(ch)[0] == "C" or (ch.isspace() and ch != " "):
            raise _refuse("control, format or exotic whitespace character")
    text = " ".join(text.split())
    if not text:
        raise _refuse("empty")
    if len(text) > MAX_CHARS:
        raise _refuse("too long")
    for sequence in _BANNED_SEQUENCES:
        if sequence in text:
            raise _refuse(f"sequence {sequence!r}")
    stack: list[str] = []
    tokens = 0
    previous = ""  # class of the previous token: word | symbol | close
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        tokens += 1
        if tokens > MAX_TOKENS:
            raise _refuse("too many tokens")
        if ch == " ":
            i += 1
            continue
        if text.startswith("!![", i):
            stack.append("M")
            i += 3
            previous = "symbol"
            continue
        if ch in _QUOTE_LIKE:
            raise _refuse("quote, backtick, antiquotation or '#'")
        match = _NUMERAL.match(text, i) if ch.isascii() and ch.isdigit() else None
        if match:
            i = match.end()
            previous = "word"
            continue
        if _IDENT_START.match(ch) or (not ch.isascii() and _char_class(ch) == "word"):
            ident = _IDENT.match(text, i)
            if ident is None:  # a non-ASCII digit-like start: treat as one word character
                i += 1
                previous = "word"
                continue
            j = ident.end()
            while (
                j + 1 < n
                and text[j] == "."
                and (_IDENT_START.match(text[j + 1]) or text[j + 1].isdigit())
            ):
                nxt = _IDENT.match(text, j + 1) or _NUMERAL.match(text, j + 1)
                if nxt is None:
                    break
                j = nxt.end()
            name = text[i:j]
            if name not in ALLOWED_KEYWORDS:
                _ident_ok(name)
            i, previous = j, "word"
            continue
        if ch.isascii() and ch.isdigit():  # unreachable (numeral handled), kept for safety
            raise _refuse("bad numeral")
        if ch == "'":
            raise _refuse("quote or character literal")
        if ch == "\\":
            if i + 1 < n and text[i + 1] == " " and i > 0 and text[i - 1] == " ":
                i += 1
                previous = "symbol"
                continue
            raise _refuse("backslash escape")
        if ch == ";":
            if stack and stack[-1] == "M":
                i += 1
                previous = "symbol"
                continue
            raise _refuse("';' outside a matrix literal")
        if ch == "@":
            if i + 1 < n and (_IDENT_START.match(text[i + 1]) or text[i + 1] in "(⟨"):
                i += 1
                previous = "symbol"
                continue
            raise _refuse("'@' not followed by an identifier")
        if ch == ".":
            if text.startswith("..", i):
                i += 2
                previous = "symbol"
                continue
            if (
                previous in {"word", "close"}
                and i + 1 < n
                and (text[i + 1].isalnum() or text[i + 1] in "{_")
            ):
                i += 1
                previous = "symbol"
                continue
            raise _refuse("stray '.'")
        if ch in _OPEN:
            stack.append(ch)
            i += 1
            previous = "symbol"
            continue
        if ch in _CLOSE or ch == "]" and stack and stack[-1] == "M":
            if ch == "]" and stack and stack[-1] == "M":
                stack.pop()
            elif not stack or stack[-1] != _CLOSE[ch]:
                raise _refuse("unbalanced brackets")
            else:
                stack.pop()
            i += 1
            previous = "close"
            continue
        if ch in _ASCII_SYMBOLS or (not ch.isascii() and _char_class(ch) == "symbol"):
            i += 1
            previous = "symbol"
            continue
        raise _refuse(f"character {ch!r}")
    if stack:
        raise _refuse("unbalanced brackets")
    return text

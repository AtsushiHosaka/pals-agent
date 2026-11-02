"""Fail-closed token policy for untrusted Lean sources, applied before any compiler runs.

A Lean command can run arbitrary code during elaboration, so a process exit status alone proves
nothing. This policy is what keeps candidate code from executing; ``pals_agent.lean_audit`` is the
independent post-check. The forms were enumerated from the parser categories and token table of the
pinned Lean/Mathlib environment and are repeated by ``pals-api`` for Recipe admission.

The lexer is intentionally not a full Lean lexer. Wherever Lean and this lexer could disagree about
where a literal or comment ends, the source is rejected rather than interpreted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Every pinned `#` command name has at least four letters and starts in lowercase. Three letters
# here fails closed on unknown commands, while `#s`, `#xs`, `#α`, `#(s ∪ t)`, `#{x | p x}`, `#[1]`
# and `#v[1]` stay available as cardinality notation and literals.
_NUMBER_SIGN_COMMAND = re.compile(r"#[a-z_][A-Za-z0-9_!?']{2,}")
# Lean's own identifier characters. `\w` would also count a token such as `ᶜ`, which Lean ends at,
# so `∅ᶜinfix` would hide the command after it.
_IDENTIFIER_LETTER = (
    "A-Za-z_\u0391-\u039f\u03a1\u03a2\u03a4-\u03a9\u03b1-\u03ba\u03bc-\u03fb\u1f00-\u1ffe"
    "\u2100-\u214f\u2080-\u2089\u2090-\u209c\u1d62-\u1d6a\u2c7c\U0001d49c-\U0001d59f"
)
_WORD_START = rf"(?<![{_IDENTIFIER_LETTER}])"
_WORD_END = rf"(?![{_IDENTIFIER_LETTER}0-9'!?])"
_NATIVE_EVALUATION = re.compile(
    _WORD_START
    + r"(native_decide|nativeDecide|bv_decide|bv_check|ofReduceBool|ofReduceNat|reduceBool"
    r"|reduceNat|trustCompiler)"
    + _WORD_END
    + r"|(\+native)"
    + _WORD_END
    + "|"
    + _WORD_START
    + r"(native\s*:=\s*true)"
)
_METAPROGRAMMING = re.compile(
    _WORD_START
    + r"(run_cmd|run_elab|run_meta|run_tac|run_conv|by_elab|elab|elab_rules|elab_stx_quot"
    r"|term_elab|command_elab|tactic_elab|macro|macro_rules|syntax|mixfix|notation|notation3"
    r"|infix|infixl|infixr|binder_predicate|initialize|builtin_\w+|declare_\w+|register_\w+"
    r"|grind_propagator|eval_expr|def_eval_config_item|init_quot|include_str"
    r"|add_aesop_rules|erase_aesop_rules|compile_def|compile_inductive|lrat_proof|from_lrat"
    r"|polyrith|cadical|sudo|unlock_limits|implemented_by|extern|csimp|unsafe\w*"
    r"|IO|EIO|BaseIO|EST|Lean\.Elab|Lean\.Meta|Lean\.Parser"
    r"|(?:open|export)\s+private)"
    + _WORD_END
    # `List.prefix` and similar names stay usable; the commands need a precedence, name or `=>`.
    + "|"
    + _WORD_START
    + r"(prefix|postfix)"
    + _WORD_END
    + r"(?=\s*(?::|\(|=>))"
)
# `eval%` and its relatives run or compile a term at elaboration time; `%` ends the word.
_EVALUATING_TERM = re.compile(
    _WORD_START + r"(eval|elabToSyntax|compile_def|compile_inductive|mk_rpc_widget)%"
)
_IDENTIFIER_RUN = re.compile(rf"[{_IDENTIFIER_LETTER}0-9'!?]+")
_MODULE_HEADER = re.compile(r"\A\s*(module)" + _WORD_END)
_SYNTAX_QUOTATION = re.compile(r"`[(\[]")
_ATTRIBUTE_START = re.compile(r"@\[|" + _WORD_START + r"attribute\s*\[")
_ATTRIBUTE_NAME = re.compile(r"[^\s(\[{]+")
_ATTRIBUTE_APPLIES_ATTRIBUTES = re.compile(r"\(\s*attr\s*:=")
_ALLOWED_ATTRIBUTES = frozenset(
    {
        "always_inline",
        "cases_eliminator",
        "coe",
        "congr",
        "continuity",
        "default_instance",
        "deprecated",
        "elab_as_elim",
        "ext",
        "field_simps",
        "fun_prop",
        "gcongr",
        "grind",
        "induction_eliminator",
        "inline",
        "instance",
        "irreducible",
        "match_pattern",
        "measurability",
        "mono",
        "nolint",
        "norm_cast",
        "push_cast",
        "reducible",
        "refl",
        "semireducible",
        "simp",
        "simps",
        "specialize",
        "symm",
        "to_additive",
        "trans",
    }
)
_OPTION = re.compile(_WORD_START + r"set_option\s+(\S+)")
_ALLOWED_OPTIONS = frozenset(
    {
        "autoImplicit",
        "maxHeartbeats",
        "maxRecDepth",
        "push_neg.use_distrib",
        "relaxedAutoImplicit",
        "synthInstance.maxHeartbeats",
        "synthInstance.maxSize",
    }
)
_ALLOWED_OPTION_PREFIXES = ("backward.", "linter.", "pp.")
_AESOP = re.compile(_WORD_START + r"aesop\w*\??(?![\w'])")
_AESOP_ADD = re.compile(r"\s*add")
_THEOREM_NAME_PART = r"(?:«[^»\n]*»|[^\s:({\[⦃.«»]+)"
_THEOREM = re.compile(
    r"(?<![\w.«'])(?:theorem|lemma)\s+("
    + _THEOREM_NAME_PART
    + r"(?:\."
    + _THEOREM_NAME_PART
    + r")*)"
)
_EXAMPLE = re.compile(r"(?<![\w.«'])(?:noncomputable\s+)?example(?![\w'!?])")
_COMMAND_START = re.compile(
    r"^(?:@\[[^\n]*?\]\s*)*(?:(?:private|protected|noncomputable|partial|nonrec|local|scoped)\s+)*"
    r"(?P<command>[A-Za-z_]+|#)",
    re.MULTILINE,
)
_STATEMENT_COMMANDS = frozenset({"theorem", "lemma"})
_DEFINITION_COMMANDS = frozenset({"def", "abbrev", "structure", "inductive", "class"})
_SCOPE_COMMANDS = frozenset({"open", "namespace", "section", "end", "universe", "set_option"})
_COMMANDS = _STATEMENT_COMMANDS | _DEFINITION_COMMANDS | _SCOPE_COMMANDS | frozenset(
    {
        "#", "add_decl_doc", "alias", "attribute", "axiom", "constant", "deriving", "example",
        "export", "import", "include", "instance", "mutual", "omit", "opaque", "prelude",
        "unsafe", "variable",
    }
)
_AUDITED_EXAMPLE = re.compile(r"noncomputable\s+def\s+pals_audit_\d+")
_LET_WORD = re.compile(r"(?<![\w'.])let(?![\w'!?])")
_SIGNATURE_OPENING = "([{⦃⟨"
_SIGNATURE_CLOSING = ")]}⦄⟩"
_UNSAFE_QUOTED_NAME = re.compile(r'["#«\n]|--|/-')
_OPENING = "([{"
_CLOSING = ")]}"


@dataclass(frozen=True, slots=True)
class SourceViolation:
    code: str
    message: str


def strip_lean_comments_and_strings(source: str) -> str:
    """Return executable text with comments and string contents removed, keeping line breaks."""
    return _lex(source)[0]


def find_source_violation(source: str) -> SourceViolation | None:
    """Return the first forbidden construct in ``source``, or ``None`` when it may be compiled."""
    code, ambiguity = _lex(source)
    if ambiguity is not None:
        return SourceViolation(
            "lean.disallowed_ambiguous_lexing",
            f"Generated Lean code contains an ambiguous literal: {ambiguity}.",
        )
    for pattern, diagnostic, label in (
        (_NUMBER_SIGN_COMMAND, "lean.disallowed_interactive_command", "an interactive command"),
        (_MODULE_HEADER, "lean.disallowed_metaprogramming", "metaprogramming command"),
        (_NATIVE_EVALUATION, "lean.disallowed_native_evaluation", "native evaluation"),
        (_METAPROGRAMMING, "lean.disallowed_metaprogramming", "metaprogramming command"),
        (_EVALUATING_TERM, "lean.disallowed_metaprogramming", "metaprogramming command"),
    ):
        match = pattern.search(code)
        if match is not None:
            return SourceViolation(
                diagnostic, f"Generated Lean code contains {label} `{match.group(0).strip()}`."
            )
    for word in _IDENTIFIER_RUN.finditer(code):
        if "simproc" in word.group(0):
            return SourceViolation(
                "lean.disallowed_metaprogramming",
                f"Generated Lean code contains metaprogramming command `{word.group(0)}`.",
            )
    if _SYNTAX_QUOTATION.search(code) is not None:
        return SourceViolation(
            "lean.disallowed_syntax_quotation", "Generated Lean code contains syntax quotation."
        )
    closing_brackets = _closing_brackets(code)
    return (
        _attribute_violation(code, closing_brackets)
        or _option_violation(code)
        or _aesop_violation(code, closing_brackets)
    )


def declared_theorem_names(source: str) -> tuple[str, ...]:
    """Return the names written after ``theorem`` or ``lemma``, without enclosing namespaces."""
    return tuple(
        match.group(1).removeprefix("_root_.")
        for match in _THEOREM.finditer(strip_lean_comments_and_strings(source))
    )


def with_auditable_examples(source: str) -> str:
    """Name each ``example`` for the audit compile, because Lean discards examples after checking.

    ``noncomputable def`` accepts data and an omitted type as ``example`` does, which ``theorem``
    does not. The attested source is never changed.
    """
    masked = _masked_code(source)
    pieces: list[str] = []
    position = 0
    for index, match in enumerate(_EXAMPLE.finditer(masked)):
        pieces += [source[position : match.start()], f"noncomputable def pals_audit_{index}"]
        position = match.end()
    pieces.append(source[position:])
    return "".join(pieces)


def statement_reference(source: str) -> str | None:
    """Return ``source`` with proofs as ``sorry`` and only self-evident commands kept.

    Comments and literals are blank, so nothing Lean and this lexer read differently survives. The
    trusted audit elaborates the result over the imports alone. A statement that needs a dropped
    command fails to elaborate, and one it silently changed compiles to a different type; both are
    rejected. ``None`` means a declaration's statement could not be located.
    """
    code = _masked_code(source)
    starts = [
        (match.start(), match.group("command"))
        for match in _COMMAND_START.finditer(code)
        if match.group("command") in _COMMANDS
    ]
    kept: list[str] = []
    pending: list[str] = []
    ends = [start for start, _ in starts[1:]] + [len(code)]
    for (start, command), end in zip(starts, ends, strict=False):
        text = code[start:end].strip()
        if command in _STATEMENT_COMMANDS or _AUDITED_EXAMPLE.search(text):
            restated = _restated_declaration(text)
            if restated is None:
                return None
            kept += [*pending, restated] if restated else []
        elif command in _DEFINITION_COMMANDS:
            kept += [*pending, text]
        elif command in _SCOPE_COMMANDS:
            if text.endswith((" in", "\nin")):
                pending.append(text)
                continue
            kept.append(text)
        pending = []
    return "\n".join(kept) + "\n"


def _restated_declaration(text: str) -> str | None:
    """Return the declaration with a ``sorry`` body, ``""`` if an example states no type."""
    example = _AUDITED_EXAMPLE.search(text)
    theorem = None if example else _THEOREM.search(text)
    head = example or theorem
    if head is None:
        return None
    signature = _signature(text, head.end())
    if signature is None:
        return "" if example else None
    title = example.group(0) if example else f"theorem {theorem.group(1)}"  # type: ignore[union-attr]
    return f"{title}{signature} := sorry"


def _signature(text: str, start: int) -> str | None:
    """Return binders and type up to the top-level ``:=`` or first pattern-matching alternative."""
    depth = 0
    pending_lets = 0
    has_type = False
    index = start
    while index < len(text):
        character = text[index]
        if character in _SIGNATURE_OPENING:
            depth += 1
        elif character in _SIGNATURE_CLOSING:
            depth -= 1
        elif depth == 0:
            if text.startswith(":=", index):
                if pending_lets == 0:
                    return text[start:index].rstrip() if has_type else None
                pending_lets -= 1
                index += 2
                continue
            if character == ":":
                has_type = True
            elif _LET_WORD.match(text, index):
                pending_lets += 1
            elif (
                character == "|"
                and has_type
                and not text[text.rfind("\n", start, index) + 1 : index].strip()
            ):
                return text[start:index].rstrip()
        index += 1
    return None


def _masked_code(source: str) -> str:
    """Blank comments and string contents while keeping every character offset."""
    masked = list(source)
    index = 0
    while index < len(source):
        end = _literal_end(source, index)
        if end is None:
            index += 1
            continue
        for position in range(index, end):
            masked[position] = " "
        index = end
    return "".join(masked)


def _literal_end(source: str, index: int) -> int | None:
    pair = source[index : index + 2]
    if pair == "--":
        newline = source.find("\n", index)
        return len(source) if newline < 0 else newline
    if pair == "/-":
        depth = 1
        # `/--` and `/-!` open doc comments, so their `-` or `!` cannot start the closing `-/`.
        position = index + (3 if source[index + 2 : index + 3] in ("-", "!") else 2)
        while position < len(source) and depth:
            pair = source[position : position + 2]
            if pair in ("/-", "-/"):
                depth += 1 if pair == "/-" else -1
                position += 2
            else:
                position += 1
        return position
    if source[index] == '"':
        position = index + 1
        while position < len(source):
            if source[position] == "\\":
                position += 2
            elif source[position] == '"':
                return position + 1
            else:
                position += 1
        return len(source)
    return None


def _lex(source: str) -> tuple[str, str | None]:
    output: list[str] = []
    ambiguity: str | None = None
    index = 0
    length = len(source)
    last_visible = ""

    def flag(reason: str) -> None:
        nonlocal ambiguity
        ambiguity = ambiguity or reason

    while index < length:
        character = source[index]
        pair = source[index : index + 2]
        # A symbol before `--` or `/-` may end a longer Lean token, as in `<--` and `//-`, which
        # then opens no comment. An adjoining comment must also still separate the words around it.
        if pair in ("--", "/-"):
            if index and not _comment_may_follow(source[index - 1]):
                flag("comment syntax attached to a preceding symbol")
            output.append(" ")
        if pair == "--":
            newline = source.find("\n", index)
            if newline < 0:
                break
            index = newline
            continue
        if pair == "/-":
            depth = 1
            index += 3 if source[index + 2 : index + 3] in ("-", "!") else 2
            while index < length and depth:
                pair = source[index : index + 2]
                if pair == "/-":
                    depth += 1
                    index += 2
                elif pair == "-/":
                    depth -= 1
                    index += 2
                else:
                    if source[index] == "\n":
                        output.append("\n")
                    index += 1
            if depth:
                flag("unterminated block comment")
            continue
        if character == '"':
            previous = source[index - 1] if index else " "
            # Excludes `'"'`, `'\"'`, raw `r"`/`r#"` and interpolated `s!"` strings, each of which
            # Lean tokenizes differently from a plain string opening here.
            if previous.isalnum() or previous in "_'!?#\\»`.":
                flag("string quote attached to a preceding token")
            # `s! "{...}"` is interpolation: the blanked contents would be code to Lean.
            if last_visible == "!":
                flag("string quote following an interpolation prefix")
            output.append(" ")
            index += 1
            terminated = False
            while index < length:
                current = source[index]
                if current == "\\":
                    if source[index + 1 : index + 2] == "\n":
                        output.append("\n")
                    index += 2
                    continue
                index += 1
                if current == '"':
                    terminated = True
                    break
                if current == "\n":
                    output.append("\n")
            if not terminated:
                flag("unterminated string")
            continue
        if character == "«":
            # Excludes the character literal `'«'`, which is not a quoted identifier opening.
            if index and source[index - 1] == "'":
                flag("quoted identifier attached to an apostrophe")
            closing = source.find("»", index + 1)
            if closing < 0:
                flag("unterminated quoted identifier")
                output.append(source[index:])
                break
            quoted = source[index + 1 : closing]
            if _UNSAFE_QUOTED_NAME.search(quoted) is not None:
                flag("quoted identifier containing literal or comment syntax")
            output.append(source[index : closing + 1])
            index = closing + 1
            continue
        output.append(character)
        if not character.isspace():
            last_visible = character
        index += 1
    return "".join(output), ambiguity


def _comment_may_follow(character: str) -> bool:
    return character.isspace() or character.isalnum() or character in "_'!?()[]{}⟨⟩⦃⦄,;."


def _closing_brackets(code: str) -> dict[int, int]:
    """Map each opening bracket to its closing one once, so nested input stays linear."""
    closing: dict[int, int] = {}
    stack: list[int] = []
    for index, character in enumerate(code):
        if character in _OPENING:
            stack.append(index)
        elif character in _CLOSING and stack:
            closing[stack.pop()] = index
    return closing


def _attribute_violation(code: str, closing_brackets: dict[int, int]) -> SourceViolation | None:
    if _ATTRIBUTE_APPLIES_ATTRIBUTES.search(code) is not None:
        return SourceViolation(
            "lean.disallowed_attribute", "Generated Lean code applies attributes through `attr`."
        )
    for start in _ATTRIBUTE_START.finditer(code):
        opening = start.end() - 1
        closing = closing_brackets.get(opening)
        if closing is None:
            return SourceViolation(
                "lean.disallowed_attribute", "Generated Lean code has an unclosed attribute list."
            )
        for entry in _top_level_entries(code[opening + 1 : closing]):
            name = _attribute_name(entry)
            if name not in _ALLOWED_ATTRIBUTES:
                return SourceViolation(
                    "lean.disallowed_attribute",
                    f"Generated Lean code uses attribute `{name}` outside the allowlist.",
                )
    return None


def _top_level_entries(body: str) -> list[str]:
    entries: list[str] = []
    depth = 0
    current: list[str] = []
    for character in body:
        if character in _OPENING:
            depth += 1
        elif character in _CLOSING:
            depth -= 1
        if character == "," and depth == 0:
            entries.append("".join(current))
            current = []
        else:
            current.append(character)
    entries.append("".join(current))
    return entries


def _attribute_name(entry: str) -> str:
    text = entry.strip()
    for kind in ("local ", "scoped "):
        text = text.removeprefix(kind).lstrip()
    text = text.removeprefix("-").lstrip()
    match = _ATTRIBUTE_NAME.match(text)
    return match.group(0) if match is not None else ""


def _option_violation(code: str) -> SourceViolation | None:
    for match in _OPTION.finditer(code):
        name = match.group(1)
        if name not in _ALLOWED_OPTIONS and not name.startswith(_ALLOWED_OPTION_PREFIXES):
            return SourceViolation(
                "lean.disallowed_option",
                f"Generated Lean code sets option `{name}` outside the allowlist.",
            )
    return None


def _aesop_violation(code: str, closing_brackets: dict[int, int]) -> SourceViolation | None:
    """Reject inline Aesop rules: a `tactic` rule builder evaluates a candidate-defined constant."""
    for match in _AESOP.finditer(code):
        index = match.end()
        while True:
            while index < len(code) and code[index].isspace():
                index += 1
            if index >= len(code) or code[index] != "(":
                break
            closing = closing_brackets.get(index)
            if closing is None:
                break
            if _AESOP_ADD.match(code, index + 1) is not None:
                return SourceViolation(
                    "lean.disallowed_metaprogramming",
                    "Generated Lean code adds an inline Aesop rule.",
                )
            index = closing + 1
    return None

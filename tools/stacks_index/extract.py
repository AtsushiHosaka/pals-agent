"""Source-level declaration extractor for the AxiomMath Stacks formalization.

Nothing here builds or elaborates Lean. Declarations, signatures, docstrings, Stacks tags and the
module a declaration lives in are read from the `.lean` text. The result is therefore a *lexical*
approximation: names are namespace-qualified but not resolved against `open`, types are the
source signature (plus the `variable` binders that the signature depends on), and nothing here
establishes that a statement is true or that it applies. Only Lean can decide that.

`add_to_stacks TAG DECL` lines tag declarations that live upstream (Mathlib). They are kept as
`upstream` entries (name and tag only); the statement of those lives in the Mathlib index.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

TAG_PATTERN = re.compile(r"[0-9A-Z]{4}")
_ATTR_STACKS = re.compile(r'\bstacks(?:_fixed)?\s+([0-9A-Z]{4})(?:\s+"((?:[^"\\]|\\.)*)")?')
_ATTR_EGA_SGA = re.compile(r'\b(ega|sga)\s+"((?:[^"\\]|\\.)*)"(?:\s+"((?:[^"\\]|\\.)*)")?')
_DOC_TAG = re.compile(
    r"(?:\bTag\s+|stacks\.math\.columbia\.edu/tag/|\bStacks(?:\s+Project)?(?:\s+tag)?\s+)"
    r"([0-9A-Z]{4})\b"
)
_ADD_TO_STACKS = re.compile(
    r'add_to_stacks\s+([0-9A-Z]{4})(?:\s+"((?:[^"\\]|\\.)*)")?\s+(\S+)', re.DOTALL
)
_ADD_TO_REF = re.compile(
    r'add_to_(ega|sga)\s+"((?:[^"\\]|\\.)*)"(?:\s+"((?:[^"\\]|\\.)*)")?\s+(\S+)', re.DOTALL
)
_IDENT = re.compile(r"[A-Za-z_À-￿][A-Za-z0-9_'!?À-￿.]*")
_WORD_BOUND = re.compile(r"[A-Za-z_À-￿][A-Za-z0-9_'!?À-￿]*")
_CHAR_LITERAL = re.compile(r"'(?:\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)|[^\\'\n])'")
_SCAN_START = re.compile(r"--|/-|\"|'")
_SIG_TOKEN = re.compile(r"[()\[\]{}⟨⟩⦃⦄]|:=|\bwhere\b|\n[ \t]*\|")

DECL_KEYWORDS = frozenset(
    {
        "theorem",
        "lemma",
        "def",
        "abbrev",
        "instance",
        "structure",
        "class",
        "inductive",
        "axiom",
        "opaque",
        "irreducible_def",
    }
)
MODIFIERS = frozenset(
    {
        "public",
        "private",
        "protected",
        "noncomputable",
        "nonrec",
        "partial",
        "unsafe",
        "meta",
        "local",
        "scoped",
    }
)
_OTHER_COMMANDS = frozenset(
    {
        "namespace",
        "section",
        "end",
        "variable",
        "universe",
        "open",
        "export",
        "attribute",
        "add_to_stacks",
        "add_to_ega",
        "add_to_sga",
        "include",
        "omit",
        "set_option",
        "alias",
        "example",
        "notation",
        "infix",
        "infixl",
        "infixr",
        "prefix",
        "postfix",
        "macro",
        "macro_rules",
        "syntax",
        "elab",
        "declare_syntax_cat",
        "initialize",
        "builtin_initialize",
        "import",
        "module",
        "mutual",
        "run_cmd",
        "library_note",
        "register_simp_attr",
        "simproc",
        "deriving",
    }
)
COMMAND_STARTERS = DECL_KEYWORDS | MODIFIERS | _OTHER_COMMANDS
_IN_PREFIX = frozenset(
    {"open", "set_option", "attribute", "variable", "include", "omit", "universe"}
)
_KIND_OF = {
    "theorem": "theorem",
    "lemma": "theorem",
    "def": "def",
    "irreducible_def": "def",
    "abbrev": "abbrev",
    "instance": "instance",
    "structure": "structure",
    "class": "class",
    "inductive": "inductive",
    "axiom": "axiom",
    "opaque": "opaque",
}
MAX_SIGNATURE = 3000
MAX_BODY = 6000
MAX_DOC = 4000


@dataclass(frozen=True, slots=True)
class Tag:
    tag: str
    comment: str
    source: str  # "attribute" | "add_to_stacks" | "docstring"


@dataclass(slots=True)
class Declaration:
    name: str
    kind: str
    module: str
    path: str
    line: int
    signature: str
    context: str
    doc: str
    body: str
    attrs: list[str]
    tags: list[Tag] = field(default_factory=list)
    refs: list[tuple[str, str, str]] = field(default_factory=list)  # (ega|sga, ref, comment)
    namespace: str = ""


@dataclass(slots=True)
class UpstreamLink:
    """A tag attached by `add_to_stacks` to a declaration not defined in this file."""

    target: str
    namespace: str
    tag: Tag
    module: str
    path: str
    line: int


@dataclass(slots=True)
class ModuleInfo:
    module: str
    path: str
    title: str
    doc: str
    lines: int
    tags: list[str]


@dataclass(slots=True)
class FileResult:
    module: ModuleInfo
    declarations: list[Declaration]
    upstream: list[UpstreamLink]
    skipped: dict[str, int]


@dataclass(slots=True)
class _Comment:
    start: int
    end: int
    kind: str  # "doc" | "module" | "block" | "line"
    body: str


def _blank(segment: str) -> str:
    return re.sub(r"[^\n]", " ", segment)


def mask_source(text: str) -> tuple[str, list[_Comment]]:
    """Blank out comments and string contents (same offsets), and report the comments."""
    out: list[str] = []
    comments: list[_Comment] = []
    position = 0
    scan = 0
    length = len(text)
    while True:
        match = _SCAN_START.search(text, scan)
        if match is None:
            break
        start = match.start()
        token = match.group()
        if token == "'":
            literal = _CHAR_LITERAL.match(text, start)
            previous = text[start - 1] if start else " "
            if literal is None or previous.isalnum() or previous in "_'":
                scan = start + 1
                continue
            out.append(text[position:start])
            out.append("'" + " " * (literal.end() - start - 2) + "'")
            position = scan = literal.end()
        elif token == '"':
            end = start + 1
            while end < length and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            end = min(end, length - 1)
            out.append(text[position : start + 1])
            out.append(_blank(text[start + 1 : end]))
            out.append('"' if end < length else "")
            position = scan = end + 1
        elif token == "--":
            end = text.find("\n", start)
            end = length if end < 0 else end
            comments.append(_Comment(start, end, "line", text[start + 2 : end]))
            out.append(text[position:start])
            out.append(" " * (end - start))
            position = scan = end
        else:
            depth = 1
            cursor = start + 2
            while depth and cursor < length:
                opened = text.find("/-", cursor)
                closed = text.find("-/", cursor)
                if closed < 0:
                    cursor = length
                    break
                if 0 <= opened < closed:
                    depth += 1
                    cursor = opened + 2
                else:
                    depth -= 1
                    cursor = closed + 2
            end = cursor
            third = text[start + 2 : start + 3]
            kind = "doc" if third == "-" else "module" if third == "!" else "block"
            body_start = start + (3 if kind != "block" else 2)
            comments.append(_Comment(start, end, kind, text[body_start : max(body_start, end - 2)]))
            out.append(text[position:start])
            out.append(_blank(text[start:end]))
            position = scan = end
    out.append(text[position:])
    return "".join(out), comments


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _matching(text: str, start: int, opener: str, closer: str) -> int:
    """Index just past the bracket that closes `text[start]` (end of text if unbalanced)."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


_PAIRS = {"(": ")", "{": "}", "[": "]", "⦃": "⦄", "⟨": "⟩"}


@dataclass(frozen=True, slots=True)
class Binder:
    names: tuple[str, ...]
    text: str


def split_binders(masked: str, original: str | None = None, *, bare: bool = True) -> list[Binder]:
    """Top-level bracketed binder groups `(a b : T)`, `{x : T}`, `[inst : C x]`, `⦃x⦄`."""
    source = original if original is not None else masked
    binders: list[Binder] = []
    index = 0
    while index < len(masked):
        char = masked[index]
        if char in "({[⦃":
            end = _matching(masked, index, char, _PAIRS[char])
            body = masked[index + 1 : end - 1]
            colon = _first_top_level_colon(body)
            head = body[:colon] if colon is not None else ("" if char == "[" or not bare else body)
            names = tuple(_WORD_BOUND.findall(head))
            binders.append(Binder(names, _normalize(source[index:end])))
            index = end
        else:
            index += 1
    return binders


def _first_top_level_colon(text: str) -> int | None:
    depth = 0
    for index, char in enumerate(text):
        if char in "([{⟨⦃":
            depth += 1
        elif char in ")]}⟩⦄":
            depth -= 1
        elif char == ":" and depth == 0 and text[index + 1 : index + 2] != "=":
            return index
    return None


def relevant_context(variables: list[Binder], signature: str) -> str:
    """The `variable` binders a declaration with this signature depends on (Lean 4 rule).

    A named binder is kept when the signature (or an already kept binder) mentions one of its
    names; an instance binder `[C x]` is kept when every variable it mentions is kept.
    """
    if not variables:
        return ""
    plain_names = {n for b in variables if not b.text.startswith("[") for n in b.names}
    colon = _first_top_level_colon(signature)
    head = signature if colon is None else signature[:colon]
    shadowed = {name for binder in split_binders(head, bare=False) for name in binder.names}
    mentioned = set(_WORD_BOUND.findall(signature)) - shadowed
    included: set[int] = set()
    kept_names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for index, binder in enumerate(variables):
            if index in included:
                continue
            idents = set(_WORD_BOUND.findall(binder.text))
            if binder.text.startswith("["):
                dependencies = idents & plain_names
                hit = bool(dependencies) and dependencies <= kept_names
            else:
                hit = bool(set(binder.names) & mentioned)
            if hit:
                included.add(index)
                if not binder.text.startswith("["):
                    kept_names |= set(binder.names)
                mentioned |= idents
                changed = True
    return " ".join(variables[index].text for index in sorted(included))


def _signature_end(masked_rest: str) -> tuple[int, str]:
    """Offset of the first top-level `:=` / `where` / pattern bar, and which one it was."""
    depth = 0
    for match in _SIG_TOKEN.finditer(masked_rest):
        token = match.group()
        if token in "([{⟨⦃":
            depth += 1
        elif token in ")]}⟩⦄":
            depth -= 1
        elif depth <= 0:
            return match.start(), "where" if token == "where" else "def"
    return len(masked_rest), "end"


def _split_top_level(masked: str, original: str, separator: str = ",") -> list[str]:
    """Split `original` at top-level separators, found on the comment/string-masked text."""
    parts: list[str] = []
    depth = 0
    last = 0
    for index, char in enumerate(masked):
        if char in "([{⟨⦃":
            depth += 1
        elif char in ")]}⟩⦄":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(original[last:index])
            last = index + 1
    parts.append(original[last:])
    return [part.strip() for part in parts if part.strip()]


def _parse_attributes(
    attr_blocks: list[tuple[str, str]],
) -> tuple[list[str], list[Tag], list[tuple[str, str, str]]]:
    names: list[str] = []
    tags: list[Tag] = []
    refs: list[tuple[str, str, str]] = []
    for masked, original in attr_blocks:
        for item in _split_top_level(masked, original):
            head = _WORD_BOUND.match(item)
            if head is None:
                continue
            word = head.group()
            if word in {"stacks", "stacks_fixed"}:
                for match in _ATTR_STACKS.finditer(item):
                    tags.append(Tag(match.group(1), match.group(2) or "", "attribute"))
            elif word in {"ega", "sga"}:
                for match in _ATTR_EGA_SGA.finditer(item):
                    refs.append((match.group(1), match.group(2), match.group(3) or ""))
            else:
                names.append(word)
    return names, tags, refs


def module_name(path: Path, root: Path) -> str:
    return ".".join(path.relative_to(root).with_suffix("").parts)


def _merge_attribute_lines(masked: str, starts: list[int]) -> list[int]:
    """Drop the start of a command when the previous command is only `@[...]` attributes."""
    ends = [*starts[1:], len(masked)]
    merged: list[int] = []
    drop_next = False
    for begin, end in zip(starts, ends, strict=True):
        if drop_next:
            drop_next = False
            continue
        merged.append(begin)
        text = masked[begin:end].strip()
        while text.startswith("@["):
            text = text[_matching(text, 1, "[", "]") :].strip()
        if text == "" and masked[begin:end].strip().startswith("@["):
            drop_next = True
    return merged


def _command_ranges(masked: str) -> list[int]:
    """Offsets where a top-level command starts (column 0, known command word or `@[`)."""
    starts: list[int] = []
    offset = 0
    for line in masked.split("\n"):
        if line and not line[0].isspace():
            if line.startswith("@["):
                starts.append(offset)
            else:
                word = _WORD_BOUND.match(line)
                if word is not None and word.group() in COMMAND_STARTERS or line[0] == "#":
                    starts.append(offset)
        offset += len(line) + 1
    return starts


@dataclass(slots=True)
class _Scope:
    kind: str
    name: str
    variables: list[Binder] = field(default_factory=list)


class _FileState:
    def __init__(self) -> None:
        self.stack: list[_Scope] = [_Scope("file", "")]

    @property
    def namespace(self) -> str:
        return ".".join(s.name for s in self.stack if s.kind == "namespace" and s.name)

    def variables(self) -> list[Binder]:
        return [binder for scope in self.stack for binder in scope.variables]


def _doc_tags(doc: str) -> list[Tag]:
    seen: dict[str, None] = {}
    for match in _DOC_TAG.finditer(doc):
        tag = match.group(1)
        if any(char.isdigit() for char in tag):
            seen.setdefault(tag)
    return [Tag(tag, "", "docstring") for tag in seen]


def _clean_doc(body: str) -> str:
    return body.strip()[:MAX_DOC]


def extract_text(
    text: str, *, module: str, path: str, skipped: dict[str, int] | None = None
) -> FileResult:
    """Extract declarations from one Lean source file."""
    skipped = skipped if skipped is not None else {}
    masked, comments = mask_source(text)
    line_starts = [0]
    for match in re.finditer("\n", text):
        line_starts.append(match.end())

    def line_of(offset: int) -> int:
        return bisect.bisect_right(line_starts, offset)

    docs_by_next: dict[int, _Comment] = {}
    for comment in comments:
        if comment.kind == "doc":
            following = re.compile(r"\S").search(masked, comment.end)
            if following is not None:
                docs_by_next[following.start()] = comment
    module_doc = "\n\n".join(c.body.strip() for c in comments if c.kind == "module")
    title = ""
    for line in module_doc.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            title = stripped
            break
    starts = _merge_attribute_lines(masked, _command_ranges(masked))
    starts.append(len(masked))
    state = _FileState()
    declarations: list[Declaration] = []
    upstream: list[UpstreamLink] = []
    pending_variables: list[Binder] = []
    pending_prefix = False
    for begin, end in zip(starts, starts[1:], strict=False):
        command = masked[begin:end]
        original = text[begin:end]
        stripped = command.strip()
        word_match = _WORD_BOUND.match(stripped)
        first = word_match.group() if word_match else ""
        was_prefix = pending_prefix
        pending_prefix = False
        if first in _IN_PREFIX and re.search(r"\bin\s*$", stripped):
            pending_prefix = True
            if first == "variable":
                pending_variables = split_binders(
                    re.sub(r"\bin\s*$", "", command[command.find("variable") + 8 :]),
                    re.sub(r"\bin\s*$", "", original[original.find("variable") + 8 :]),
                )
            continue
        is_section = re.match(
            r"(?:@\[[^\]]*\]\s*)*(?:(?:public|noncomputable|meta|private)\s+)*section\b", stripped
        )
        if first in {"namespace", "mutual"} or is_section:
            name = ""
            if first == "namespace":
                words = stripped.split()
                name = words[1] if len(words) > 1 else ""
            state.stack.append(_Scope("namespace" if first == "namespace" else "section", name))
            continue
        if first == "end":
            if len(state.stack) > 1:
                state.stack.pop()
            continue
        if first == "variable":
            state.stack[-1].variables.extend(
                split_binders(
                    command[command.find("variable") + 8 :],
                    original[original.find("variable") + 8 :],
                )
            )
            continue
        if first == "add_to_stacks":
            link_match = _ADD_TO_STACKS.match(original.strip())
            if link_match:
                upstream.append(
                    UpstreamLink(
                        target=link_match.group(3),
                        namespace=state.namespace,
                        tag=Tag(link_match.group(1), link_match.group(2) or "", "add_to_stacks"),
                        module=module,
                        path=path,
                        line=line_of(begin),
                    )
                )
            continue
        if first in {"add_to_ega", "add_to_sga"}:
            ref_match = _ADD_TO_REF.match(original.strip())
            if ref_match:
                upstream.append(
                    UpstreamLink(
                        target=ref_match.group(4),
                        namespace=state.namespace,
                        tag=Tag(
                            "",
                            "",
                            f"add_to_{ref_match.group(1)}:{ref_match.group(2)}"
                            f"|{ref_match.group(3) or ''}",
                        ),
                        module=module,
                        path=path,
                        line=line_of(begin),
                    )
                )
            continue
        parsed = _parse_declaration(command, original, begin, state, was_prefix, pending_variables)
        pending_variables = [] if was_prefix else pending_variables
        if parsed is None:
            if first == "alias":
                skipped["alias"] = skipped.get("alias", 0) + 1
            elif first == "example":
                skipped["example"] = skipped.get("example", 0) + 1
            continue
        if isinstance(parsed, str):
            skipped[parsed] = skipped.get(parsed, 0) + 1
            continue
        doc_comment = docs_by_next.get(begin)
        doc = _clean_doc(doc_comment.body) if doc_comment else ""
        parsed.doc = doc
        parsed.line = line_of(begin + parsed.line)  # parsed.line held an offset inside command
        parsed.module = module
        parsed.path = path
        tags = list(parsed.tags)
        known = {t.tag for t in tags}
        tags.extend(t for t in _doc_tags(doc) if t.tag not in known)
        parsed.tags = tags
        declarations.append(parsed)
    tag_ids = sorted(
        {t.tag for d in declarations for t in d.tags}
        | {u.tag.tag for u in upstream if u.tag.tag}
        | {
            m.group(1)
            for m in _DOC_TAG.finditer(module_doc)
            if any(c.isdigit() for c in m.group(1))
        }
    )
    info = ModuleInfo(
        module=module,
        path=path,
        title=title,
        doc=module_doc[:MAX_DOC],
        lines=text.count("\n") + 1,
        tags=tag_ids,
    )
    return FileResult(info, declarations, upstream, skipped)


def _parse_declaration(
    command: str,
    original: str,
    begin: int,
    state: _FileState,
    was_prefix: bool,
    extra_variables: list[Binder],
) -> Declaration | str | None:
    position = 0
    attr_blocks: list[tuple[str, str]] = []
    modifiers: set[str] = set()
    keyword = ""
    while True:
        while position < len(command) and command[position].isspace():
            position += 1
        if command.startswith("@[", position):
            end = _matching(command, position + 1, "[", "]")
            attr_blocks.append((command[position + 2 : end - 1], original[position + 2 : end - 1]))
            position = end
            continue
        word = _WORD_BOUND.match(command, position)
        if word is None:
            return None
        text = word.group()
        if text in MODIFIERS:
            modifiers.add(text)
            position = word.end()
        elif text in DECL_KEYWORDS:
            keyword = text
            keyword_offset = position
            position = word.end()
            break
        else:
            return None
    if keyword == "class":
        inductive = re.compile(r"\s+(inductive|abbrev)\b").match(command, position)
        if inductive:
            position = inductive.end()
    rest_start = position
    while rest_start < len(command) and command[rest_start].isspace():
        rest_start += 1
    if keyword == "instance":
        priority = re.compile(r"\(priority\s*:=[^)]*\)\s*").match(command, rest_start)
        if priority:
            rest_start = priority.end()
    first_char = command[rest_start : rest_start + 1]
    name_end = rest_start
    if (
        first_char
        and first_char not in ":([{⦃⟨"
        and command[rest_start:].split(None, 1)[0]
        not in {
            "where",
            ":=",
        }
    ):
        while name_end < len(command) and command[name_end] not in " \t\n(){}[]⟨⟩⦃⦄:,=|":
            name_end += 1
    raw_name = command[rest_start:name_end].rstrip(".")
    brace = re.compile(r"\{[^}]*\}").match(command, name_end)
    if brace and command[name_end - 1 : name_end] == ".":
        name_end = brace.end()
    if keyword == "instance" and not raw_name:
        return "anonymous_instance"
    if not raw_name:
        return "unparsed"
    if "private" in modifiers:
        return "private"
    if raw_name.startswith("_root_."):
        full_name = raw_name[len("_root_.") :]
    else:
        namespace = state.namespace
        full_name = f"{namespace}.{raw_name}" if namespace else raw_name
    rest_masked = command[name_end:]
    rest_original = original[name_end:]
    stop, how = _signature_end(rest_masked)
    signature = _normalize(rest_original[:stop])[:MAX_SIGNATURE]
    body = ""
    if keyword in {"structure", "class", "inductive"} and how in {"where", "def"}:
        body = rest_original[stop:].strip()[:MAX_BODY]
    elif how == "where":
        body = ""
    attrs, tags, refs = _parse_attributes(attr_blocks)
    variables = state.variables() + (extra_variables if was_prefix else [])
    context = relevant_context(variables, signature)
    return Declaration(
        name=full_name,
        kind=_KIND_OF[keyword],
        module="",
        path="",
        line=keyword_offset,
        signature=signature,
        context=context,
        doc="",
        body=body,
        attrs=attrs,
        tags=tags,
        refs=refs,
        namespace=state.namespace,
    )


def extract_file(path: Path, root: Path) -> FileResult:
    text = path.read_text(encoding="utf-8", errors="replace")
    return extract_text(text, module=module_name(path, root), path=str(path.relative_to(root)))


def iter_lean_files(root: Path, layer: str) -> Iterable[Path]:
    return sorted((root / layer).rglob("*.lean"))

"""Small, capture-avoiding universal instantiation for retrieved OpenMath.

This checks a proposed application, not a mathematical proof. In particular it
never upgrades an LLM-assessed answer to Lean-verified evidence.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

NS = "http://www.openmath.org/OpenMath"
_INTEGER = re.compile(r"-?(?:0|[1-9][0-9]{0,30})\Z")


class InstantiationError(ValueError):
    pass


def _tag(node: ET.Element) -> str:
    return node.tag.removeprefix("{" + NS + "}")


def _parse(source: str) -> ET.Element:
    if not isinstance(source, str) or not 0 < len(source.encode()) <= 32768:
        raise InstantiationError("OpenMath size invalid")
    if "<!" in source:
        raise InstantiationError("OpenMath declarations forbidden")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        raise InstantiationError("OpenMath malformed") from error
    nodes = list(root.iter())
    if len(nodes) > 1024 or any(
        not isinstance(node.tag, str) or not node.tag.startswith("{" + NS + "}") for node in nodes
    ):
        raise InstantiationError("OpenMath namespace or node budget invalid")

    def depth(node: ET.Element, level: int = 0) -> None:
        if level > 48:
            raise InstantiationError("OpenMath depth invalid")
        for child in node:
            depth(child, level + 1)

    depth(root)
    return root


def _name(declaration: ET.Element) -> str:
    if _tag(declaration) == "OMV":
        name = declaration.get("name")
    elif _tag(declaration) == "OMATTR" and len(declaration) == 2:
        return _name(declaration[1])
    else:
        raise InstantiationError("Unsupported binder declaration")
    if not name or len(name) > 128:
        raise InstantiationError("Invalid binder name")
    return name


def _domain_symbol(node: ET.Element) -> str | None:
    if _tag(node) != "OMS":
        return None
    if node.get("cd") == "setname1":
        return {"N": "Nat", "Z": "Int", "R": "Real"}.get(node.get("name", ""))
    if node.get("cd") in {"typed1", "types1"}:
        return {"Nat": "Nat", "Int": "Int", "Real": "Real"}.get(node.get("name", ""))
    return None


def _declared_domains(root: ET.Element) -> dict[str, str]:
    domains: dict[str, str] = {}

    def declare(name: str, domain: str) -> None:
        if name in domains and domains[name] != domain:
            # Never widen Nat to Real due to a later redundant or conflicting premise.
            raise InstantiationError("Parameter has multiple domain constraints")
        domains[name] = domain

    node = root[0] if _tag(root) == "OMOBJ" and len(root) == 1 else root
    while True:
        if _tag(node) == "OMBIND" and len(node) == 3:
            for declaration in node[1]:
                if _tag(declaration) == "OMATTR" and len(declaration) == 2:
                    sorts = [
                        domain for item in declaration[0].iter() if (domain := _domain_symbol(item))
                    ]
                    if len(sorts) == 1:
                        declare(_name(declaration), sorts[0])
            node = node[2]
            continue
        # Follow only the theorem's implication spine, not arbitrary nested
        # consequents, disjunctions, negations or other locally scoped assertions.
        if (
            _tag(node) == "OMA"
            and len(node) == 3
            and node[0].get("name") == "implies"
            and node[0].get("cd") == "logic1"
        ):
            for premise in _conjuncts(node[1]):
                if (
                    _tag(premise) == "OMA"
                    and len(premise) == 3
                    and premise[0].get("cd") == "set1"
                    and premise[0].get("name") == "in"
                    and _tag(premise[1]) == "OMV"
                ):
                    domain = _domain_symbol(premise[2])
                    if domain:
                        declare(_name(premise[1]), domain)
            node = node[2]
            continue
        break
    return domains


def _conjuncts(node: ET.Element) -> list[ET.Element]:
    if (
        _tag(node) == "OMA"
        and len(node) >= 2
        and node[0].get("cd") == "logic1"
        and node[0].get("name") == "and"
    ):
        return [part for child in list(node)[1:] for part in _conjuncts(child)]
    return [node]


def _variables(root: ET.Element) -> set[str]:
    return {str(n.get("name")) for n in root.iter() if _tag(n) == "OMV"}


def _rename_scope(node: ET.Element, old: str, new: str) -> None:
    if (
        _tag(node) == "OMBIND"
        and len(node) == 3
        and old in {_name(declaration) for declaration in node[1]}
    ):
        return  # A nested binder owns a different variable with this spelling.
    if _tag(node) == "OMV" and node.get("name") == old:
        node.set("name", new)
    for child in node:
        _rename_scope(child, old, new)


@dataclass(frozen=True, slots=True)
class Instantiation:
    openmath_xml: str
    substitutions: tuple[dict[str, str], ...]


def _leading_universal_parameters(root: ET.Element) -> tuple[set[str], dict[str, int]]:
    eligible: set[str] = set()
    owners: dict[str, int] = {}
    body = root[0]
    while _tag(body) == "OMBIND" and len(body) == 3:
        if body[0].get("name") != "forall" or body[0].get("cd") not in {"quant1", "typed1"}:
            break
        for declaration in body[1]:
            name = _name(declaration)
            if name in eligible:
                raise InstantiationError("Shadowed universal parameter is ambiguous")
            eligible.add(name)
            owners[name] = id(body)
        body = body[2]
    return eligible, owners


def universal_numeric_parameters(source: str) -> tuple[dict[str, str], ...]:
    """Describe supported leading numeric parameters, without verifying the theorem.

    A function's lambda input and an existential witness are never parameters for
    this operation. Unknown sorts and ambiguous shadowed names are not offered.
    The eventual application still passes through instantiate_universal.
    """
    root = _parse(source)
    if _tag(root) != "OMOBJ" or len(root) != 1:
        raise InstantiationError("Universal instantiation input invalid")
    eligible, _ = _leading_universal_parameters(root)
    if not eligible:
        return ()
    domains = _declared_domains(root)
    declarations = [
        _name(declaration)
        for binding in root.iter()
        if _tag(binding) == "OMBIND" and len(binding) == 3
        for declaration in binding[1]
    ]
    return tuple(
        {"variable": variable, "domain": domains[variable]}
        for variable in sorted(eligible)
        if variable in domains and declarations.count(variable) == 1
    )


def instantiate_universal(
    source: str, substitutions: list[dict[str, str]], *, target: str = ""
) -> Instantiation:
    """Instantiate leading universally bound numeric parameters, preserving premises.

    Unknown sorts, existential witnesses, and compound untyped terms are deliberately
    not guessed. Other reasoning remains possible as a separately assessed derivation.
    """
    root = _parse(source)
    if _tag(root) != "OMOBJ" or len(root) != 1 or not 1 <= len(substitutions) <= 8:
        raise InstantiationError("Universal instantiation input invalid")
    domains = _declared_domains(root)
    target_domains = _declared_domains(_parse(target)) if target else {}
    eligible, owners = _leading_universal_parameters(root)
    replacements: dict[str, ET.Element] = {}
    records: list[dict[str, str]] = []
    for item in substitutions:
        if not isinstance(item, dict) or set(item) != {"variable", "term_openmath_xml"}:
            raise InstantiationError("Substitution fields invalid")
        variable = item["variable"]
        if variable not in eligible or variable in replacements:
            raise InstantiationError("Substitution is not a unique universal parameter")
        declarations = [
            declaration
            for binding in root.iter()
            if _tag(binding) == "OMBIND" and len(binding) == 3
            for declaration in binding[1]
            if _name(declaration) == variable
        ]
        if len(declarations) != 1:
            raise InstantiationError("Shadowed parameter identity is ambiguous")
        term = _parse(item["term_openmath_xml"])
        if _tag(term) == "OMOBJ" and len(term) == 1:
            term = term[0]
        required = domains.get(variable)
        if required is None:
            raise InstantiationError("Substitution parameter sort unknown")
        if _tag(term) == "OMI" and not len(term) and _INTEGER.fullmatch(term.text or ""):
            if required == "Nat" and int(term.text or "0") < 0:
                raise InstantiationError("Negative integer cannot instantiate Nat")
        elif _tag(term) == "OMV" and not len(term):
            if target_domains.get(_name(term)) != required:
                raise InstantiationError("Substitution variable sort differs or is unknown")
        else:
            raise InstantiationError("Substitution term sort cannot be established")
        replacements[variable] = term
        records.append(dict(item, domain=required))
    all_names = _variables(root) | set().union(*(_variables(t) for t in replacements.values()))
    free_in_terms = set().union(*(_variables(t) for t in replacements.values()))

    def transform(node: ET.Element, active: dict[str, ET.Element]) -> ET.Element:
        if _tag(node) == "OMV" and node.get("name") in active:
            return copy.deepcopy(active[str(node.get("name"))])
        if _tag(node) == "OMBIND" and len(node) == 3:
            declarations = list(node[1])
            names = {_name(d) for d in declarations}
            applied = {name for name in names & set(active) if owners.get(name) == id(node)}
            # Repeated spelling below another binder must never be replaced.
            active = {
                key: value for key, value in active.items() if key not in names or key in applied
            }
            for declaration in declarations:
                name = _name(declaration)
                if name in applied:
                    node[1].remove(declaration)
                elif name in free_in_terms:
                    suffix = 1
                    while f"{name}_pals{suffix}" in all_names:
                        suffix += 1
                    renamed = f"{name}_pals{suffix}"
                    all_names.add(renamed)
                    _rename_scope(declaration, name, renamed)
                    _rename_scope(node[2], name, renamed)
            node[2] = transform(node[2], active)
            if not len(node[1]):
                return node[2]
            return node
        for index, child in enumerate(list(node)):
            node[index] = transform(child, active)
        return node

    transformed = transform(root, replacements)
    return Instantiation(ET.tostring(transformed, encoding="unicode"), tuple(records))

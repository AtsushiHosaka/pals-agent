"""Fail-closed OpenMath validation for ``typed-commutative-algebra-modules-v1``.

The profile is deliberately separate from the ideal-lattice profile.  Its
dependent module and linear-map sorts make scalar, domain, and codomain
mistakes explicit instead of silently coercing them.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from importlib import resources
from typing import Literal, cast

from .openmath import (
    OPENMATH_NAMESPACE,
    OPENMATH_STANDARD_CDBASE,
    MathXMLValidationError,
    _canonicalize_openmath_v4_root,
    _element_depth,
    _local_name,
    _openmath_parents,
    _operator_symbol,
    validate_openmath_xml,
)

TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE = (
    "urn:pals:openmath:typed-commutative-algebra-modules:v1"
)
TYPED_COMMUTATIVE_ALGEBRA_MODULES_PROFILE = "typed-commutative-algebra-modules-v1"

_SortName = Literal["prop", "comm_ring", "module", "submodule", "linear_map"]
_Symbol = tuple[str, str, str]
_BINDERS = frozenset({"forall", "exists"})
_ALLOWED_ATTRIBUTES: dict[str, frozenset[str]] = {
    "OMOBJ": frozenset({"version"}),
    "OMS": frozenset({"cdbase", "cd", "name"}),
    "OMV": frozenset({"name"}),
    "OMA": frozenset(),
    "OMBIND": frozenset(),
    "OMBVAR": frozenset(),
    "OMATTR": frozenset(),
    "OMATP": frozenset(),
}


@dataclass(frozen=True, slots=True)
class CommutativeAlgebraModuleSort:
    """A profile sort with every dependent carrier named explicitly."""

    name: _SortName
    ring: str | None = None
    module: str | None = None
    codomain: str | None = None

    def render(self) -> str:
        if self.name == "prop":
            return "Prop"
        if self.name == "comm_ring":
            return "CommRing"
        if self.name == "module":
            return f"Module({self.ring or '?'})"
        if self.name == "submodule":
            return f"Submodule({self.ring or '?'},{self.module or '?'})"
        return f"LinearMap({self.ring or '?'},{self.module or '?'},{self.codomain or '?'})"


_PROP = CommutativeAlgebraModuleSort("prop")


def _load_symbol_registry() -> frozenset[_Symbol]:
    try:
        payload = json.loads(
            resources.files("pals_agent.content_dictionaries")
            .joinpath("typed-commutative-algebra-modules-v1-registry.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - package invariant
        raise RuntimeError("typed commutative-algebra modules registry is unavailable.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "pals.typed-commutative-algebra-modules-registry.v1"
        or payload.get("profile_id") != TYPED_COMMUTATIVE_ALGEBRA_MODULES_PROFILE
        or payload.get("cdbases")
        != {
            "standard": OPENMATH_STANDARD_CDBASE,
            "typed": TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE,
        }
        or not isinstance(payload.get("symbols"), list)
    ):  # pragma: no cover - package invariant
        raise RuntimeError("typed commutative-algebra modules registry header is invalid.")
    symbols: set[_Symbol] = set()
    for entry in payload["symbols"]:
        if not isinstance(entry, dict):  # pragma: no cover - package invariant
            raise RuntimeError("typed commutative-algebra modules registry entry is invalid.")
        identity = tuple(entry.get(key) for key in ("cdbase", "cd", "name"))
        if not all(isinstance(value, str) and value for value in identity):
            raise RuntimeError("typed commutative-algebra modules registry identity is invalid.")
        symbols.add(cast(_Symbol, identity))
    if len(symbols) != len(payload["symbols"]):  # pragma: no cover - package invariant
        raise RuntimeError("typed commutative-algebra modules registry contains duplicates.")
    return frozenset(symbols)


_SYMBOL_REGISTRY = _load_symbol_registry()


def canonicalize_typed_commutative_algebra_modules_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed module-theory proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the typed module-theory byte bound.")
    root = validate_openmath_xml(xml)
    validate_typed_commutative_algebra_modules_openmath_root(root)
    return _canonicalize_openmath_v4_root(root)


def validate_canonical_typed_commutative_algebra_modules_openmath_xml(xml: str) -> str:
    """Accept only exact canonical bytes for this isolated profile."""
    if ' xmlns:n0=""' in xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed module-theory canonical bytes."
        )
    canonical = canonicalize_typed_commutative_algebra_modules_openmath_xml(xml)
    if canonical != xml:
        raise MathXMLValidationError(
            "OpenMath XML is not exact typed module-theory canonical bytes."
        )
    return canonical


def validate_typed_commutative_algebra_modules_openmath_xml(xml: str) -> None:
    """Validate a closed ``typed-commutative-algebra-modules-v1`` proposition."""
    validate_typed_commutative_algebra_modules_openmath_root(validate_openmath_xml(xml))


def validate_typed_commutative_algebra_modules_openmath_root(root: ET.Element) -> None:
    """Validate an already OpenMath-core-valid root under this profile."""
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath typed module-theory tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    _validate_tree_shape(nodes, parents=parents)
    if len(list(root)) != 1:
        raise MathXMLValidationError("typed module-theory OMOBJ must contain one expression.")
    if not _contains_profile_construct(root, parents=parents):
        raise MathXMLValidationError("OpenMath XML is not a typed module-theory proposition.")
    inferred = _infer_expression(list(root)[0], environment={}, parents=parents, path="root")
    _require_sort("typed module-theory root", inferred, _PROP, path="root")


def _validate_tree_shape(nodes: list[ET.Element], *, parents: dict[ET.Element, ET.Element]) -> None:
    for element in nodes:
        local = _local_name(element)
        if local not in _ALLOWED_ATTRIBUTES:
            raise MathXMLValidationError(
                f"OpenMath element `{local}` is outside typed module-theory."
            )
        _validate_attributes(element, local=local)
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath typed module-theory tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("typed module-theory text exceeds 20,000 code points.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("typed module-theory elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError(
                "typed module-theory attribute exceeds 20,000 code points."
            )
        if local == "OMATTR":
            parent = parents.get(element)
            if (
                parent is None
                or _local_name(parent) != "OMBVAR"
                or not _is_type_declaration(element, parents=parents)
            ):
                raise MathXMLValidationError(
                    "typed module-theory permits OMATTR only as a typed OMBVAR declaration."
                )
        if local == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                not _is_type_declaration(item, parents=parents) for item in declarations
            ):
                raise MathXMLValidationError(
                    "typed module-theory OMBVAR requires 1..256 typed OMV declarations."
                )
        if local == "OMBIND":
            children = list(element)
            symbol = _operator_symbol(children[0], parents=parents) if len(children) == 3 else None
            if (
                symbol is None
                or symbol[:2] != (TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE, "typed1")
                or symbol[2] not in _BINDERS
                or children[0].get("cdbase") != TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE
            ):
                raise MathXMLValidationError(
                    "typed module-theory OMBIND must use typed1:forall or typed1:exists."
                )
        if local == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("typed module-theory OMA head must be an OMS.")
        if local == "OMS":
            _validate_symbol(element, parents=parents)


def _validate_attributes(element: ET.Element, *, local: str) -> None:
    actual = set(element.attrib)
    unexpected = actual - _ALLOWED_ATTRIBUTES[local]
    if unexpected:
        raise MathXMLValidationError(
            f"typed module-theory `{local}` does not permit attribute `{sorted(unexpected)[0]}`."
        )
    if local == "OMOBJ" and actual != {"version"}:
        raise MathXMLValidationError("typed module-theory OMOBJ requires only `version`.")
    if local == "OMS" and not {"cd", "name"}.issubset(actual):
        raise MathXMLValidationError("typed module-theory OMS requires `cd` and `name`.")
    if local == "OMV" and actual != {"name"}:
        raise MathXMLValidationError("typed module-theory OMV requires only `name`.")


def _validate_symbol(element: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> None:
    symbol = _operator_symbol(element, parents=parents)
    if symbol is None:
        raise MathXMLValidationError("typed module-theory OMS must identify a symbol.")
    direct_cdbase = element.get("cdbase")
    if symbol[0] == TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE:
        if direct_cdbase != symbol[0]:
            raise MathXMLValidationError(
                "typed module-theory OMS must directly declare its typed cdbase."
            )
    elif symbol[0] == OPENMATH_STANDARD_CDBASE and direct_cdbase is None:
        ancestor = parents.get(element)
        while ancestor is not None:
            if "cdbase" in ancestor.attrib:
                raise MathXMLValidationError(
                    "Standard typed module-theory OMS may omit cdbase only without inheritance."
                )
            ancestor = parents.get(ancestor)
    if symbol not in _SYMBOL_REGISTRY:
        _base, cd, name = symbol
        raise MathXMLValidationError(f"Symbol `{cd}:{name}` is outside typed module-theory.")


def _contains_profile_construct(root: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    type_annotation = False
    binder = False
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None or symbol[0] != TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE:
            continue
        type_annotation |= symbol[1:] == ("typed1", "type")
        binder |= symbol[1:] in {("typed1", "forall"), ("typed1", "exists")}
    return type_annotation and binder


def _is_type_declaration(declaration: ET.Element, *, parents: dict[ET.Element, ET.Element]) -> bool:
    if _local_name(declaration) != "OMATTR" or len(list(declaration)) != 2:
        return False
    attributes, variable = list(declaration)
    if _local_name(attributes) != "OMATP" or _local_name(variable) != "OMV":
        return False
    pair = list(attributes)
    return (
        len(pair) == 2
        and _local_name(pair[0]) == "OMS"
        and _operator_symbol(pair[0], parents=parents)
        == (TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE, "typed1", "type")
    )


def _infer_expression(
    expression: ET.Element,
    *,
    environment: dict[str, CommutativeAlgebraModuleSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> CommutativeAlgebraModuleSort:
    local = _local_name(expression)
    if local == "OMV":
        name = expression.get("name")
        if name is None or name not in environment:
            raise MathXMLValidationError(
                f"typed module-theory has a free or undeclared variable `{name or ''}` at {path}."
            )
        return environment[name]
    if local == "OMBIND":
        return _infer_binding(expression, environment=environment, parents=parents, path=path)
    if local != "OMA":
        raise MathXMLValidationError(f"typed module-theory cannot infer `{local}` at {path}.")
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        raise MathXMLValidationError(f"typed module-theory OMA has an invalid operator at {path}.")
    inferred = [
        _infer_expression(
            argument, environment=environment, parents=parents, path=f"{path}/{index}"
        )
        for index, argument in enumerate(arguments, start=1)
    ]
    return _infer_application(symbol, inferred, path=path)


def _infer_binding(
    binding: ET.Element,
    *,
    environment: dict[str, CommutativeAlgebraModuleSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> CommutativeAlgebraModuleSort:
    _binder, variables, body = list(binding)
    local_environment = dict(environment)
    declared: set[str] = set()
    for index, declaration in enumerate(list(variables), start=1):
        name, sort = _parse_declaration(
            declaration,
            environment=local_environment,
            parents=parents,
            path=f"{path}/bind/{index}",
        )
        if name in declared or name in environment:
            raise MathXMLValidationError(
                f"typed module-theory redeclares bound variable `{name}` at {path}."
            )
        declared.add(name)
        local_environment[name] = sort
    body_sort = _infer_expression(
        body, environment=local_environment, parents=parents, path=f"{path}/body"
    )
    _require_sort("typed binder body", body_sort, _PROP, path=path)
    return _PROP


def _parse_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, CommutativeAlgebraModuleSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> tuple[str, CommutativeAlgebraModuleSort]:
    attributes, variable = list(declaration)
    _type, sort_expression = list(attributes)
    name = variable.get("name")
    if name is None or not name:
        raise MathXMLValidationError(f"typed module-theory bound OMV is missing `name` at {path}.")
    sort = _parse_sort(sort_expression, environment=environment, parents=parents, path=path)
    if sort.name == "comm_ring":
        return name, CommutativeAlgebraModuleSort("comm_ring", ring=name)
    if sort.name == "module":
        return name, CommutativeAlgebraModuleSort("module", ring=sort.ring, module=name)
    if sort.name == "submodule":
        return name, CommutativeAlgebraModuleSort("submodule", ring=sort.ring, module=sort.module)
    if sort.name == "linear_map":
        return name, sort
    raise MathXMLValidationError("typed module-theory cannot bind a proposition.")


def _parse_sort(
    expression: ET.Element,
    *,
    environment: dict[str, CommutativeAlgebraModuleSort],
    parents: dict[ET.Element, ET.Element],
    path: str,
) -> CommutativeAlgebraModuleSort:
    if _local_name(expression) == "OMS" and _operator_symbol(expression, parents=parents) == (
        TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE,
        "module1",
        "CommRing",
    ):
        return CommutativeAlgebraModuleSort("comm_ring")
    if _local_name(expression) != "OMA":
        raise MathXMLValidationError(
            f"typed module-theory has an invalid type annotation at {path}."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    names = [_bound_name(argument) for argument in arguments]
    if symbol == (TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE, "module1", "Module"):
        _require_type_arity(symbol, names, exact=1)
        ring = _require_declared_ring(names[0], environment=environment, path=path)
        return CommutativeAlgebraModuleSort("module", ring=ring.ring)
    if symbol == (TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE, "module1", "Submodule"):
        _require_type_arity(symbol, names, exact=2)
        return _declared_submodule_sort(names, environment=environment, path=path)
    if symbol == (TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE, "module1", "LinearMap"):
        _require_type_arity(symbol, names, exact=3)
        ring = _require_declared_ring(names[0], environment=environment, path=path)
        domain = _require_declared_module(
            names[1], ring=ring.ring, environment=environment, path=path
        )
        codomain = _require_declared_module(
            names[2], ring=ring.ring, environment=environment, path=path
        )
        return CommutativeAlgebraModuleSort(
            "linear_map", ring=ring.ring, module=domain.module, codomain=codomain.module
        )
    raise MathXMLValidationError(f"typed module-theory has an invalid type annotation at {path}.")


def _bound_name(expression: ET.Element) -> str:
    if _local_name(expression) != "OMV" or not expression.get("name"):
        raise MathXMLValidationError(
            "typed module-theory dependent sort arguments must be bound OMVs."
        )
    return str(expression.get("name"))


def _declared_submodule_sort(
    names: list[str], *, environment: dict[str, CommutativeAlgebraModuleSort], path: str
) -> CommutativeAlgebraModuleSort:
    ring = _require_declared_ring(names[0], environment=environment, path=path)
    module = _require_declared_module(names[1], ring=ring.ring, environment=environment, path=path)
    return CommutativeAlgebraModuleSort("submodule", ring=ring.ring, module=module.module)


def _require_declared_ring(
    name: str, *, environment: dict[str, CommutativeAlgebraModuleSort], path: str
) -> CommutativeAlgebraModuleSort:
    declared = environment.get(name)
    if declared is None or declared.name != "comm_ring":
        raise MathXMLValidationError(
            "typed module-theory type annotation at "
            f"{path} requires previously bound CommRing `{name}`."
        )
    return declared


def _require_declared_module(
    name: str,
    *,
    ring: str | None,
    environment: dict[str, CommutativeAlgebraModuleSort],
    path: str,
) -> CommutativeAlgebraModuleSort:
    declared = environment.get(name)
    if declared is None or declared.name != "module" or declared.ring != ring:
        raise MathXMLValidationError(
            "typed module-theory type annotation at "
            f"{path} requires Module({ring or '?'}) `{name}`."
        )
    return declared


def _infer_application(
    symbol: _Symbol, arguments: list[CommutativeAlgebraModuleSort], *, path: str
) -> CommutativeAlgebraModuleSort:
    base, cd, name = symbol
    if (base, cd) == (OPENMATH_STANDARD_CDBASE, "relation1") and name in {"eq", "neq"}:
        _require_arity(symbol, arguments, exact=2)
        _require_argument(symbol, arguments, 1, arguments[0], path=path)
        return _PROP
    if (base, cd) == (OPENMATH_STANDARD_CDBASE, "logic1"):
        if name in {"and", "or"}:
            _require_arity(symbol, arguments, minimum=2)
        elif name in {"implies"}:
            _require_arity(symbol, arguments, exact=2)
        elif name == "not":
            _require_arity(symbol, arguments, exact=1)
        else:
            raise MathXMLValidationError(
                f"Unsupported typed module-theory application `{cd}:{name}` at {path}."
            )
        for index in range(len(arguments)):
            _require_argument(symbol, arguments, index, _PROP, path=path)
        return _PROP
    if (base, cd) != (TYPED_COMMUTATIVE_ALGEBRA_MODULES_OPENMATH_CDBASE, "module1"):
        raise MathXMLValidationError(
            f"Unsupported typed module-theory application `{cd}:{name}` at {path}."
        )
    if name in {"submodule_bot", "submodule_top"}:
        ring, module = _require_ring_module(symbol, arguments, exact=2, path=path)
        return CommutativeAlgebraModuleSort("submodule", ring=ring, module=module)
    if name in {"submodule_sup", "submodule_inf", "submodule_le"}:
        ring, module = _require_ring_module(symbol, arguments, exact=4, path=path)
        expected = CommutativeAlgebraModuleSort("submodule", ring=ring, module=module)
        _require_argument(symbol, arguments, 2, expected, path=path)
        _require_argument(symbol, arguments, 3, expected, path=path)
        return _PROP if name == "submodule_le" else expected
    if name == "linear_id":
        ring, module = _require_ring_module(symbol, arguments, exact=2, path=path)
        return CommutativeAlgebraModuleSort("linear_map", ring=ring, module=module, codomain=module)
    if name == "linear_zero":
        ring, domain, codomain = _require_ring_modules(
            symbol, arguments, exact=3, module_count=2, path=path
        )
        return CommutativeAlgebraModuleSort(
            "linear_map", ring=ring, module=domain, codomain=codomain
        )
    if name in {"linear_kernel", "linear_range", "linear_injective", "linear_surjective"}:
        ring, domain, codomain, linear_map = _require_linear_map(
            symbol, arguments, exact=4, path=path
        )
        del domain
        return (
            _PROP
            if name in {"linear_injective", "linear_surjective"}
            else CommutativeAlgebraModuleSort(
                "submodule",
                ring=ring,
                module=linear_map.module if name == "linear_kernel" else codomain,
            )
        )
    if name == "linear_comp":
        ring, domain, middle, codomain = _require_ring_modules(
            symbol, arguments, exact=6, module_count=3, path=path
        )
        first = CommutativeAlgebraModuleSort(
            "linear_map", ring=ring, module=domain, codomain=middle
        )
        second = CommutativeAlgebraModuleSort(
            "linear_map", ring=ring, module=middle, codomain=codomain
        )
        _require_argument(symbol, arguments, 4, first, path=path)
        _require_argument(symbol, arguments, 5, second, path=path)
        return CommutativeAlgebraModuleSort(
            "linear_map", ring=ring, module=domain, codomain=codomain
        )
    if name == "exact_at":
        ring, domain, middle, codomain = _require_ring_modules(
            symbol, arguments, exact=6, module_count=3, path=path
        )
        _require_argument(
            symbol,
            arguments,
            4,
            CommutativeAlgebraModuleSort("linear_map", ring=ring, module=domain, codomain=middle),
            path=path,
        )
        _require_argument(
            symbol,
            arguments,
            5,
            CommutativeAlgebraModuleSort("linear_map", ring=ring, module=middle, codomain=codomain),
            path=path,
        )
        return _PROP
    raise MathXMLValidationError(
        f"Unsupported typed module-theory application `{cd}:{name}` at {path}."
    )


def _require_ring_module(
    symbol: _Symbol, arguments: list[CommutativeAlgebraModuleSort], *, exact: int, path: str
) -> tuple[str, str]:
    ring, *modules = _require_ring_modules(
        symbol, arguments, exact=exact, module_count=1, path=path
    )
    return ring, modules[0]


def _require_ring_modules(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraModuleSort],
    *,
    exact: int,
    module_count: int,
    path: str,
) -> tuple[str, ...]:
    _require_arity(symbol, arguments, exact=exact)
    ring = arguments[0]
    if ring.name != "comm_ring" or ring.ring is None:
        _raise_expected(symbol, 0, ring, "CommRing", path=path)
    assert ring.ring is not None
    modules: list[str] = []
    for index in range(1, 1 + module_count):
        current = arguments[index]
        if current.name != "module" or current.ring != ring.ring or current.module is None:
            _raise_expected(symbol, index, current, f"Module({ring.ring})", path=path)
        assert current.module is not None
        modules.append(current.module)
    return (ring.ring, *modules)


def _require_linear_map(
    symbol: _Symbol, arguments: list[CommutativeAlgebraModuleSort], *, exact: int, path: str
) -> tuple[str, str, str, CommutativeAlgebraModuleSort]:
    ring, domain, codomain = _require_ring_modules(
        symbol, arguments, exact=exact, module_count=2, path=path
    )
    expected = CommutativeAlgebraModuleSort(
        "linear_map", ring=ring, module=domain, codomain=codomain
    )
    _require_argument(symbol, arguments, 3, expected, path=path)
    return ring, domain, codomain, expected


def _require_arity(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraModuleSort],
    *,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    valid = (exact is None or len(arguments) == exact) and (
        minimum is None or len(arguments) >= minimum
    )
    if valid:
        return
    _base, cd, name = symbol
    expectation = str(exact) if exact is not None else f"at least {minimum}"
    raise MathXMLValidationError(
        f"`{cd}:{name}` requires {expectation} arguments; received {len(arguments)}."
    )


def _require_type_arity(symbol: _Symbol | None, names: list[str], *, exact: int) -> None:
    if symbol is None or len(names) != exact:
        raise MathXMLValidationError("typed module-theory dependent type has invalid arity.")


def _require_argument(
    symbol: _Symbol,
    arguments: list[CommutativeAlgebraModuleSort],
    index: int,
    expected: CommutativeAlgebraModuleSort,
    *,
    path: str,
) -> None:
    actual = arguments[index]
    if actual == expected:
        return
    _raise_expected(symbol, index, actual, expected.render(), path=path)


def _raise_expected(
    symbol: _Symbol,
    index: int,
    actual: CommutativeAlgebraModuleSort,
    expected: str,
    *,
    path: str,
) -> None:
    _base, cd, name = symbol
    raise MathXMLValidationError(
        f"Argument {index + 1} of `{cd}:{name}` at {path} must have sort `{expected}`; "
        f"received `{actual.render()}`."
    )


def _require_sort(
    label: str,
    actual: CommutativeAlgebraModuleSort,
    expected: CommutativeAlgebraModuleSort,
    *,
    path: str,
) -> None:
    if actual == expected:
        return
    raise MathXMLValidationError(
        f"{label} at {path} must have sort `{expected.render()}`; received `{actual.render()}`."
    )

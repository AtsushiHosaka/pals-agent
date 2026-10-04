"""Trusted structuring hints transcribed from the six existing algebra validators.

These signatures explain syntax, not mathematical facts or example answers. The
unchanged profile validator remains authoritative and validates every model result.
"""

_COMMON = """Algebra profile grammar (signatures, not equations to assert):
Write op(a,b) as OMA with an OMS head followed by exactly those arguments in order.
Write a bare sort such as CommRing as OMS; dependent sorts such as Ideal(R) are
OMA type expressions, whose arguments must be prior bound OMV names, not terms.
Use this profile's explicit typed cdbase on every typed OMS, including typed1:type,
typed1:forall and typed1:exists. Standard relation1/logic1 use standard cdbase.
Bind carriers before objects depending on them. No free variables or shadowing.
The whole expression and every quantified body must have sort Prop. Prop in these
signatures is a result sort, not an available variable type constructor.
Carrier names are significant: objects over different named rings/modules cannot
be interchanged merely because their declarations have similar shapes.
There are no OMI/OMF numeric literals or implicit casts in these six profiles.
Do not import a symbol from another profile, even if its cd/name looks familiar.
"""

_GUIDANCE = {
    "typed-commutative-algebra-v1": """
Typed cdbase: urn:pals:openmath:typed-commutative-algebra:v1
Types: commalg1:CommRing; commalg1:Ideal(R); typed1:Elem(R), with R:CommRing.
Let I,J:Ideal(R). All following heads are commalg1:
ideal_bot(R), ideal_top(R) -> Ideal(R).
ideal_sum(R,I,J), ideal_inf(R,I,J), ideal_product(R,I,J) -> Ideal(R).
ideal_radical(R,I) -> Ideal(R).
ideal_le(R,I,J), is_prime_ideal(R,I), is_maximal_ideal(R,I) -> Prop.
There is no element arithmetic, quotient, localization, module or spectrum in this profile.
relation1:eq/neq take two exactly equal sorts; logic1:and/or take at least two Prop
arguments, implies takes two, not takes one.
""",
    "typed-commutative-algebra-modules-v1": """
Typed cdbase: urn:pals:openmath:typed-commutative-algebra-modules:v1
Types (module1): CommRing; Module(R); Submodule(R,M); LinearMap(R,M,N).
R:CommRing; M,N,L:Module(R). All type arguments refer to previously bound names.
There is no element sort here. Let U,V:Submodule(R,M), f:LinearMap(R,M,N),
g:LinearMap(R,N,L). All following heads are module1:
submodule_bot(R,M), submodule_top(R,M) -> Submodule(R,M).
submodule_sup(R,M,U,V), submodule_inf(R,M,U,V) -> Submodule(R,M).
submodule_le(R,M,U,V) -> Prop.
linear_id(R,M) -> LinearMap(R,M,M); linear_zero(R,M,N) -> LinearMap(R,M,N).
linear_kernel(R,M,N,f) -> Submodule(R,M).
linear_range(R,M,N,f) -> Submodule(R,N).
linear_injective(R,M,N,f), linear_surjective(R,M,N,f) -> Prop.
linear_comp(R,M,N,L,f,g) -> LinearMap(R,M,L): f is the first map M->N,
g is the second N->L; do not reverse these final two arguments.
exact_at(R,M,N,L,f,g) -> Prop, with the same ordered map types as linear_comp.
relation1:eq/neq take two exactly equal sorts; logic1:and/or take at least two Prop
arguments, implies takes two, not takes one.
""",
    "typed-commutative-algebra-localization-v1": """
Typed cdbase: urn:pals:openmath:typed-commutative-algebra-localization:v1
Types: localization1:CommRing; localization1:Submonoid(R);
localization1:SubmonoidElem(R,S); localization1:Localization(R,S);
commalg1:Ideal(A); typed1:Elem(A).
R is a prior CommRing, S a prior Submonoid(R), L a prior Localization(R,S).
A may be a bound base CommRing or bound Localization, not a type expression.
Let x,y:Elem(A), I,J:Ideal(A), r:Elem(R), s:SubmonoidElem(R,S).
localization1:ring_zero(A), ring_one(A) -> Elem(A).
localization1:ring_add(A,x,y), ring_mul(A,x,y) -> Elem(A).
localization1:is_unit(A,x) -> Prop.
localization1:submonoid_value(R,S,s) -> Elem(R).
localization1:loc_map(R,S,L,r), loc_fraction(R,S,L,r,s) -> Elem(L).
The denominator of loc_fraction is a SubmonoidElem(R,S), not an arbitrary Elem(R).
commalg1:ideal_top(A) -> Ideal(A); ideal_inf(A,I,J), ideal_sup(A,I,J) -> Ideal(A).
commalg1:ideal_radical(A,I) -> Ideal(A).
commalg1:ideal_le(A,I,J), ideal_mem(A,I,x), is_prime_ideal(A,I) -> Prop.
commalg1:ideal_disjoint_submonoid(R,S,I) -> Prop, where I:Ideal(R); note S before I.
commalg1:extend(R,S,L,I) -> Ideal(L), where I:Ideal(R).
commalg1:contract(R,S,L,J) -> Ideal(R), where J:Ideal(L).
Every localization prefix must use the exact base ring/submonoid of L. Distinct
bound submonoids or localizations are not interchangeable, even over the same ring.
relation1:eq/neq take two exactly equal sorts (including nominal bound identities).
logic1:and/or/implies/equivalent each take exactly two Prop arguments; no logic1:not.
""",
    "typed-commutative-algebra-integral-v1": """
Typed cdbase: urn:pals:openmath:typed-commutative-algebra-integral:v1
Types: integral1:CommRing, Domain, Field; integral1:Extension(R);
integral1:ValuationRing(K); typed1:Elem(A).
R must be a prior CommRing, Domain or Field; Extension(R) cannot use another extension
as its declared base. K must be a prior Field. E:Extension(R), V:ValuationRing(K).
A may be a bound CommRing, Domain, Field or Extension; NOT a ValuationRing.
There is no Elem(V) in this language: valuation membership uses ambient Elem(K).
Let x,y:Elem(A), r:Elem(R), z:Elem(E), k:Elem(K). All following heads are integral1:
ring_zero(A), ring_one(A) -> Elem(A).
ring_add(A,x,y), ring_sub(A,x,y), ring_mul(A,x,y) -> Elem(A).
ring_neg(A,x), ring_square(A,x) -> Elem(A).
extension_map(R,E,r) -> Elem(E).
is_integral(R,E,z), is_integral_extension(R,E) -> Prop.
field_inv(K,k) -> Elem(K); a mere Domain does not suffice for this operation.
valuation_mem(K,V,k), valuation_integrally_closed(K,V) -> Prop.
Extension and valuation operations must use their exact declared base/ambient carrier.
relation1:eq/neq take two exactly equal sorts. logic1:and/or/implies each take exactly
two Prop arguments, not takes one.
""",
    "typed-commutative-algebra-decomposition-v1": """
Typed cdbase: urn:pals:openmath:typed-commutative-algebra-decomposition:v1
Types (decomposition1): CommRing; Ideal(R); PrimaryIdeal(R); PrimeIdeal(R).
R:CommRing; I,J,H:Ideal(R); Q,Qa,Qb,Qc:PrimaryIdeal(R); P:PrimeIdeal(R).
PrimaryIdeal and PrimeIdeal are distinct sorts, not implicit Ideal subtypes.
All following heads are decomposition1:
primary_as_ideal(R,Q), prime_as_ideal(R,P) -> Ideal(R).
primary_radical_prime(R,Q) -> PrimeIdeal(R).
ideal_top(R), ideal_radical(R,I) -> Ideal(R).
ideal_inf2(R,I,J), ideal_inf3(R,I,J,H) -> Ideal(R).
ideal_le(R,I,J), is_primary_ideal(R,I), is_prime_ideal(R,I), is_radical_ideal(R,I) -> Prop.
primary_decomposition2(R,I,Qa,Qb), irredundant_decomposition2(R,I,Qa,Qb) -> Prop.
primary_decomposition3(R,I,Qa,Qb,Qc) -> Prop.
minimal_prime_over(R,P,I) -> Prop: the PrimeIdeal argument precedes the Ideal argument.
Use explicit primary_as_ideal/prime_as_ideal before passing these objects to an
Ideal-consuming operator. No lists, arbitrary-length decompositions, or element sort.
relation1:eq/neq take two exactly equal sorts. logic1:and/or take at least two Prop
arguments, implies takes two, not takes one.
""",
    "typed-commutative-algebra-chain-dimension-v1": """
Typed cdbase: urn:pals:openmath:typed-commutative-algebra-chain-dimension:v1
Types (chain1): CommRing; Ideal(R), with R a prior CommRing.
Let I,J:Ideal(R). All following heads are chain1, with case-sensitive names:
NoetherianRing(R), ArtinianRing(R), KrullDimLEZero(R), Field(R),
HilbertNoetherian(R), IteratedHilbertNoetherian(R) -> Prop.
IdealFG(R,I), PrimeIdeal(R,I), MaximalIdeal(R,I) -> Prop.
IdealSum(R,I,J), IdealInf(R,I,J), IdealProduct(R,I,J), IdealRadical(R,I) -> Ideal(R).
Field and PrimeIdeal here are predicates, NOT types. There is no numeric dimension
term or arbitrary chain constructor; do not invent one for an unsupported statement.
relation1:eq takes two exactly equal sorts; no relation1:neq.
logic1:and/implies take exactly two Prop arguments; not takes one; no logic1:or.
""",
}


def profile_guidance(profile_id: str) -> str:
    """Return only the requested algebra grammar; unknown profiles fail closed."""
    try:
        return _COMMON + _GUIDANCE[profile_id]
    except KeyError:
        raise ValueError("Unsupported algebra guidance profile") from None

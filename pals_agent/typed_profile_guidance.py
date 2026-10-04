"""Trusted serialization/type contracts, not retrieval examples or catalog answers.

These notes describe the installed validators. They do not extend their accepted
languages or change registry/admission fingerprints. Runtime validation remains
mandatory after generation. Signatures use mathematical sort names, not XML tags.
"""

from __future__ import annotations

_COMMON = """
XML serialization contract:
The represented XML tree has one <OMOBJ xmlns="http://www.openmath.org/OpenMath" version="2.0">
containing one proposition. No Markdown, comments, DTD, foreign tags, or free variables.
A symbol has shape <OMS cdbase="EXACT_REGISTRY_CDBASE" cd="CD" name="NAME"/>;
never replace the registry cdbase with an invented or standard URI. Apply a symbol
with <OMA> followed by its OMS operator and its arguments in signature order.
An OMV is <OMV name="bound_name"/>; an integer literal is <OMI>integer</OMI>.
Literal sorts and casts are profile-specific: a bare OMI is not automatically a
field element or a real number. Sort constructors are not term-level operations.
For typed forall/exists binders, use <OMBIND> with exactly: the registry binder OMS,
<OMBVAR> declarations </OMBVAR>, and proposition body. Each declaration has shape
<OMATTR><OMATP>type-key OMS, SortExpr</OMATP><OMV name="x"/></OMATTR>.
The type-key is the profile's registry symbol typed1:type (unless explicitly
specified otherwise below); SortExpr is an OMS for an atomic sort or an OMA for
a dependent sort. Bind carrier variables before dependent elements; dependent
sorts must use that exact earlier bound variable. No duplicate/shadowed names.
The geometry-complex profile is an explicit exception with implicit-sort binders.
Only listed registry symbols exist; do not invent row/vector constructors, integer
casts, inequalities, assumptions, or operations. Equality/inequality take two
same-sort terms. Listed logic and/or take at least two Props, implies/equivalent
take exactly two Props and not takes one, unless a profile narrows this below.
Signatures below give exact argument counts except explicit ellipses. Translate
the full requested proposition, including its quantifiers/witnesses, without
substituting an easier proposition or adding hypotheses to fit this language.
"""

_GUIDANCE = {
    "typed-math-matrix-v1": """
SortExpr: algebra1:Field; typed1:Elem(K); matrix1:Matrix(K, rows, columns);
matrix1:ColumnVector(K, rows). K is a previously bound Field variable.
Dimensions are direct OMI integer literals in 1..8. Bare nonnegative OMI has Nat
sort. To put numeral n in a matrix entry use matrix1:field_nat_cast(K, OMI(n))
with exactly two arguments -> Elem(K); a bare OMI entry is invalid.
matrix1 signatures (all carriers must match):
literal(K, rows, columns, e11, e12, ..., erc) -> Matrix(K,rows,columns), where
rows/columns are direct OMI dimensions and there are exactly rows*columns Elem(K)
entries in ROW-MAJOR order. This is one flat OMA, NOT nested rows or vectors.
column_literal(K, rows, e1,...,er) -> ColumnVector(K,rows), exactly rows entries.
JSON transport for literal is kind=matrix_literal with operator=matrix1:literal,
carrier=the bound Field variable, rows/columns=direct integer nodes, and entries=
a flat row-major array of Elem(K) expressions. Column literals use kind=column_literal
with carrier, rows and entries. These operators do NOT use variadic arguments.
Every entries item is a scalar expression, never a matrix: either a previously
bound Elem(K) variable, field_nat_cast, or determinant of a square matrix over K.
For a numeral entry n, use kind="binary", operator with cd="matrix1" and
name="field_nat_cast", left={kind:"variable",name:"K"},
right={kind:"integer",value:"n"} (replace K and n with the exact bound carrier
and original nonnegative integer). Include the exact registry cdbase in operator.
The cast takes two arguments named left/right, not argument1/argument2/argument3.
zero(K,n,n) is an n by n MATRIX, never the scalar n or the scalar zero.
A determinant entry uses kind="unary", operator=matrix1:determinant,
argument=its actual square-matrix expression. Do not substitute determinant or
zero for a numeric cast. Full validation checks scalar carrier and determinant shape.
Copy EVERY displayed entry of EACH explicit matrix, including the claimed result,
with its exact value, order, sign and cast. Never replace a displayed matrix by
zero, identity, a shape/type constructor, or an easier matrix. Never repair an
incorrect asserted equality into a true equality. zero and identity denote only
the zero/identity matrices explicitly requested; they are not literal placeholders.
Bare integer dimensions are separate from matrix entries: entries require the
listed field casts even for zero and one. If an entry is not representable by the
registry, do not silently discard it, approximate it, or replace it by zero.
zero(K,rows,columns) -> Matrix; identity(K,n) -> Matrix(K,n,n).
add(A,B) and neg(A) preserve matrix shape. scale(s,A) takes Elem(K) FIRST.
mul(A,B) takes exactly TWO matrices (no K/dimensions as extra arguments), with
A:Matrix(K,r,k), B:Matrix(K,k,c), result Matrix(K,r,c).
transpose(A) swaps rows/columns. determinant(A) requires square A -> Elem(K).
rank(A) -> Nat (compare to a bare OMI, not field_nat_cast).
is_inverse(A,B) -> Prop requires two same-carrier same-size square matrices and
asserts the supplied B is the two-sided inverse. Preserve both witness identities.
mul_vec(A,v): Matrix(K,r,c),ColumnVector(K,c) -> ColumnVector(K,r).
""",
    "typed-math-v1": """
SortExpr: algebra1:Group, algebra1:CommRing, algebra1:IntegralDomain, or
 typed1:Elem(S), where S is an earlier bound structure variable.
Group operations: algebra1:mul(G,x,y), inv(G,x), one(G) -> Elem(G).
Ring operations: algebra1:ring_add(R,x,y), ring_mul(R,x,y), ring_neg(R,x),
ring_zero(R), ring_one(R) -> Elem(R), for CommRing/IntegralDomain R.
The structure argument is REQUIRED even when inferable. All element arguments
belong to that exact carrier. typed1:nat_cast(R,OMI(n)) -> Elem(R), n nonnegative.
Bare OMI is Nat, not an element. Group and ring operation namespaces differ.
""",
    "typed-real-analysis-v1": """
SortExpr: typed1:Real or realanalysis1:RealFunction.
realanalysis1:lambda is an OMBIND binding exactly one typed Real variable and a
Real-valued body -> RealFunction; forall/exists require Prop bodies.
OMI is an integer literal, not Real. realanalysis1:of_int(OMI(n)) -> Real;
of_rat(OMI(p),OMI(q)) -> Real requires reduced fraction, q>0.
Real arith1 signatures: plus/times(Real,Real,...) -> Real; minus/divide(Real,Real),
abs/unary_minus(Real); power(Real,OMI(n)) with 0<=n<=64.
Listed relation1:lt/leq/gt/geq order predicates take exactly two Reals.
realanalysis1:apply(f,x)->Real; continuous_at(f,x), epsilon_delta_continuous_at(f,x),
differentiable_at(f,x)->Prop; has_deriv_at(f,point,derivative_value)->Prop;
The OpenMath point precedes the slope; Lean HasDerivAt f slope point reverses
these last two slots. Keep the published OpenMath order when structuring queries.
interval_integrable(f,lower,upper)->Prop. Here f:RealFunction, remaining args Real.
""",
    "typed-multivariable-calculus-v1": """
SortExpr: typed1:Real, multicalc1:Real2, multicalc1:Real2Function.
multicalc1:lambda2 is an OMBIND binding exactly one typed Real2 variable; its
Real-valued body yields Real2Function. forall/exists bodies are Prop.
OMI is an integer literal, not Real; multicalc1:of_int(OMI(n))->Real.
Real arith1:plus/times(a,b,...), minus(a,b), unary_minus(a), power(a,OMI(n)),
with exponent 0..64. multicalc1:pair(Real,Real)->Real2; fst/snd(Real2)->Real;
apply(Real2Function,Real2)->Real; partial_x_at/partial_y_at(f,point,value)->Prop
with f:Real2Function, point:Real2, value:Real; differentiable_at(f,point)->Prop.
""",
    "typed-ode-v1": """
Only declared sort is typed1:Real. typed1:forall body is Prop.
ode1:lambda is OMBIND binding exactly one typed Real variable, Real body ->
RealFunction. Functions are built by lambda, not unlisted function-sort declarations.
Bare OMI is an integer literal, not Real: ode1:of_int(OMI(n))->Real.
arith1 plus/times(Real,Real,...), minus(Real,Real), unary_minus(Real),
power(Real,OMI(n)) with n=0..8; transc1 exp/sin/cos(Real)->Real.
ode1:apply(f,x), deriv_at(f,x), second_deriv_at(f,x) -> Real;
initial_value(f,x,value)->Prop, f:RealFunction and x/value:Real.
relation1:eq is binary same-sort; logic1:and is exactly binary in this profile.
Mandatory whole-statement certificate shape, after optional forall Real parameters:
and(initial_value(f,of_int(OMI(0)),value), forall t:Real, eq(ODE_left,ODE_right)).
f must be a literal lambda. The global equality contains exactly one deriv_at or
second_deriv_at, evaluated at that same t; every apply uses the same t and the
same alpha-equivalent lambda as the initial clause. Initial time must be zero.
A bare derivative equality, absent initial condition, arbitrary-time initial value,
or mixed functions is outside this profile. Do not invent missing conditions.
""",
    "typed-number-theory-v1": """
SortExpr: numbertheory1:Nat or numbertheory1:Int. Bare OMI is an integer-literal
sort, not Nat/Int: nat_literal(OMI(n)) -> Nat for n>=0, int_literal(OMI(z))->Int.
All following operations are numbertheory1: nat_add/nat_mul(Nat,Nat)->Nat;
int_add/int_mul(Int,Int)->Int; int_neg(Int)->Int; int_of_nat(Nat)->Int;
gcd/lcm(Nat,Nat)->Nat; nat_mod(Nat,positive literal Nat modulus)->Nat;
congruent_nat(Nat,Nat,positive literal Nat modulus)->Prop;
divides_nat(Nat,Nat), divides_int(Int,Int), is_prime(Nat)->Prop.
Do not use an unconstrained variable as modulus or mix Nat and Int without int_of_nat.
""",
    "typed-finite-graph-v1": """
Use pals_typed_graph:forall/exists/type for binders and the OMATP type key.
SortExpr: pals_typed_graph:FinSimpleGraph, or Vertex(G), VertexClass(G), Trail(G)
for an earlier bound graph G. All graph-dependent arguments share that exact G.
Bare nonnegative OMI is Nat. All operations below use cd pals_typed_graph:
vertex_count/edge_count/degree_sum/odd_degree_count(G)->Nat;
connected/nonisolated_connected/acyclic/tree/bipartite/has_euler_trail/
has_euler_circuit(G)->Prop; nat_add/nat_mul(Nat,Nat)->Nat;
degree(G,Vertex(G))->Nat; adjacent(G,Vertex(G),Vertex(G))->Prop;
proper_bipartition(G,VertexClass(G),VertexClass(G))->Prop;
is_euler_trail/is_euler_circuit(G,Trail(G))->Prop.
Boundary restrictions override signatures: has_euler_trail/has_euler_circuit
existence families are blocked. Do not combine is_euler_trail with connected
(the admitted condition is nonisolated_connected). Full equivalent(bipartite,
proper_bipartition) families are blocked; do not weaken a request to evade this.
""",
    "typed-geometry-complex-v1": """
EXCEPTION: no OMATTR/OMATP declarations here. Use pals2:forall_real_vector2,
exists_real_vector2, forall_complex, exists_complex OMBIND with OMBVAR containing
plain OMV variables; the binder itself assigns Vector2 or Complex. Body is Prop.
OMI represents a Real integer directly. Standard arith1 plus/times take >=2 Reals,
minus/divide two Reals, abs/unary_minus one Real. Listed relation1:lt/leq/gt/geq order predicates
compare Reals. linalg2:vector(Real,Real)->Vector2;
linalg1:vector_selector(OMI(1 or 2),Vector2)->Real;
linalg1:scalarproduct(Vector2,Vector2)->Real.
complex1:complex_cartesian(Real,Real)->Complex; conjugate(Complex)->Complex;
real/imaginary/argument(Complex)->Real. nums1:i is a zero-argument application.
pals2:vector_add(Vector2,Vector2)->Vector2; vector_scale(Real,Vector2)->Vector2;
determinant2(Vector2,Vector2)->Real; complex_add/complex_mul(Complex,Complex)->Complex;
complex_norm_sq(Complex)->Real. No invented Complex arithmetic operators.
""",
    "typed-plane-geometry-v1": """
Use registry cd pals_plane_geometry for all sorts, type key, forall/exists binders and
operations: SortExpr Real, Vector2, Point2, Line2, Circle2 (distinct sorts).
Bare OMI represents Real integers. point2(Real,Real)->Point2;
vector2(Real,Real)->Vector2; vector_add(Vector2,Vector2)->Vector2;
incident_point_line(Point2,Line2), incident_point_circle(Point2,Circle2)->Prop;
parallel/perpendicular(Line2,Line2)->Prop; distance_sq(Point2,Point2)->Real;
midpoint(Point2,Point2)->Point2; reflect(Point2,Line2)->Point2;
non_collinear(Point2,Point2,Point2)->Prop. Do not coerce points to vectors or invent
constructors for lines/circles; bind them with their declared sorts.
""",
    "typed-probability-v1": """
SortExpr: typed1:Nat, typed1:Real, probability1:Probability, SampleSpace,
DistributionNat; dependent Event(S), ProbabilityMeasure(S), RealRandomVariable(S)
require an earlier SampleSpace variable S. At most one SampleSpace per statement.
OMI is nonnegative Nat. All operations below are probability1:
nat_add/nat_sub/nat_mul/nat_div/choose(Nat,Nat)->Nat; nat_to_real(Nat)->Real;
real_of_int(direct nonnegative OMI)->Real; prob_to_real(Probability)->Real;
real_add/real_mul(Real,Real,...)->Real; real_sub/real_div(Real,Real)->Real;
real_pow_nat(Real,Nat)->Real; event_intersection(Event(S),Event(S))->Event(S);
probability(ProbabilityMeasure(S),Event(S))->Probability;
constant_rv(S,Real)->RealRandomVariable(S), S must be the bound SampleSpace OMV;
expectation(constant_rv(S,value),ProbabilityMeasure(S))->Real ONLY (general RV
integrability is outside this profile); binomial_distribution(Nat,Probability)->
DistributionNat; pmf(DistributionNat,Nat)->Probability. Probability is distinct
from Real; do not construct it via a Real cast. relation1:leq only compares Nats.
""",
}


def profile_guidance(profile_id: str) -> str:
    if profile_id in _GUIDANCE:
        return _COMMON + "\nProfile signatures:\n" + _GUIDANCE[profile_id]
    from pals_agent.typed_algebra_guidance import profile_guidance as algebra_guidance

    return _COMMON + "\nProfile signatures:\n" + algebra_guidance(profile_id)

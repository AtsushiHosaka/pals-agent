"""Shared learner-facing constraints; formal targets and catalog bytes stay immutable."""

from pals_agent.curriculum_guidance import curriculum_guidance_prompt

LEARNING_POLICY = """Learner context and learning order (pals.learning-policy.v1):
Read the original request, explicit clarifications and relevant conversation context for the
requested angle units, school level, curriculum and permitted proof tools. Preserve these
constraints in any extracted/resolved task even if they do not change its mathematical truth.
Do not infer country, age, grade or curriculum from the output language, a name or location.
An explicitly elementary/lower-secondary problem needs a proof using its available tools;
do not assume a learner's level merely because the problem looks easy. Respect stated prior
knowledge and course/textbook order within a subject, including at university level. Derive
an unfamiliar auxiliary fact from available prerequisites instead of assuming a later theorem
or using the target itself circularly. Explain a necessary new concept explicitly. If no
valid proof within requested tools can be established, report that limitation or ask a focused
question; never silently change definitions, weaken the task or pretend the restriction was met.

Angle presentation: honor an explicit unit request first (including an explicit request for
radians at school level). Otherwise use degrees for elementary/lower-secondary problems and
the applicable degree-based school course; preserve explicit units in other problems. Use
radians as the general default when no such context or units are supplied. Convert angle
quantities exactly: d degrees = d*pi/180 radians. Never replace pi by 180 in lengths, areas,
coefficients or arbitrary expressions, or change a number's unit without conversion. Radian
calculus identities require rescaling when the variable is in degrees. A degree presentation
must actually explain the reasoning in degrees; appending a degree value to a radian proof
does not satisfy it. Internally Lean may still use radians and advanced libraries: preserve
the verified target, source excerpts, citations and assumptions. Bridge equivalent notation
in prose, without claiming the prose derivation was separately verified.

For stored-answer reuse, check the VERBATIM learner-facing answer against these unit and
learning-order constraints as well as mathematical scope. Exact unit equivalence alone does
not satisfy a requested presentation. If an answer needs rewriting, do not edit sealed bytes
or approve it: use the existing miss/DSP route to generate and review a suitable explanation.
Advanced internal Lean lemmas are not themselves a learner-facing learning-order violation.
Use curricular references only within their documented scope; they are guidance, not extra
mathematical hypotheses or a universal prescribed order for every learner.
""" + curriculum_guidance_prompt() + "\n\n"

LEARNING_POLICY_REVIEW = LEARNING_POLICY + """
For output review reject a learner-facing answer that violates the explicit unit/tool request
or known school prerequisites. In stored-answer scope checks set method=false for unmet
permitted-tool constraints and answer_qa/approved=false for unsuitable units or exposition,
using only fields already present in that review schema. Missing country alone is not a
reason to reject or ask: ask only if it materially changes the required tools or interpretation.
"""

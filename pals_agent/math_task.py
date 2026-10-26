"""Prompt guidance for interpreting mathematical tasks without changing contracts."""

TASK_INTERPRETATION = (
    "First identify the requested mathematical task from the current input and resolved "
    "conversation context: prove a supplied claim; compute/evaluate a value; solve for all "
    "objects satisfying conditions; determine a property/classification; decide whether a "
    "proposition is true or false; or explain a concept. "
    "A question need not contain 'prove' or supply its answer to be a complete problem. "
    "For a computation or determination, the unknown answer is the task, not a missing premise. "
    "Ask only when missing data, domain or interpretation changes the answer and context does "
    "not settle it. Preserve every supplied assumption, requested method and exact scope. "
)

PREFLIGHT_TASK_INSTRUCTION = TASK_INTERPRETATION + (
    "A 'whether', 'is it true that', '成り立つか', or 'かどうか' question asks to decide "
    "truth, not to assume the proposed claim and prove it. Keep that decision request as "
    "the goal; a counterexample to the proposed claim is a possible answer, not a reason "
    "to ask permission to answer. In premise_check, check the well-posedness of the "
    "decision task; leave counterexample empty when it only refutes the proposed answer, "
    "and preserve the question for DSP to resolve with Lean. Still ask about genuinely "
    "missing domains or assumptions that change the answer. "
    "In preflight, keep statement as a self-contained request with the unknown still unknown; "
    "do not replace it with a guessed equality, assume a candidate answer, or ask the learner "
    "to compute it. For an open question, check whether the task is well-defined, rather than "
    "treating the absence of an asserted conclusion as a false claim. Apply the subsequent "
    "literal-claim counterexample rules to assertions actually supplied by the learner, not "
    "to an answer you invented. A well-posed task with no solutions is still ready to solve. "
    "Use reason for a concise task interpretation, not hidden reasoning. For example, "
    "'Find all real solutions of sqrt(x+2)=x' is ready as a solution-set request; "
    "'What are the units of Z/12Z?' is ready as a classification request. 'Solve x^2+1=0' "
    "needs a number domain if neither the input nor context determines it. "
)

DERIVE_ANSWER_INSTRUCTION = TASK_INTERPRETATION + (
    "For compute/evaluate/solve/determine/decide tasks, derive a candidate answer before choosing "
    "the proposition to prove. State the result explicitly in the Draft with a concise "
    "checkable derivation. The answer belongs in the conclusion, never as an added hypothesis. "
    "Formalize the result for the original objects: an equality for an exact value; an iff "
    "or set equality for all solutions/classification; and attainment plus a global bound "
    "for an optimum. Prove membership and completeness for all-solutions requests, including "
    "domain restrictions and rejection of extraneous roots. An approximation must include "
    "the requested precision and an error bound; do not silently replace an exact answer by "
    "a decimal. A witness, existence statement or one-sided bound alone does not compute the "
    "requested value or full set. For sqrt(x+2)=x over the reals, derive {2}, check x>=0, "
    "and exclude the extraneous root -1. For a whether question, determine yes or no, "
    "then prove the proposed claim if true or its negation if false; provide a counterexample "
    "when it refutes the proposed claim. Refuting an existential statement requires proving "
    "that no witness exists, not exhibiting one unsuccessful candidate. "
    "A false proposed claim must never be added as a hypothesis. Preserve the decision "
    "goal and all premises; do not ask the learner to choose the desired truth value. "
    "For a supplied proof claim, preserve that claim; "
    "do not invent a numerical task. An exact user-supplied Lean harness remains fixed; "
    "do not change its proposition to fit a candidate answer. Do not invent a result when "
    "unable to derive one. "
)

ANSWER_SCOPE_REVIEW = (
    "Interpret the original task independently. A compute/solve/determine/decide question may "
    "legitimately produce a new explicit result as its conclusion even though the learner "
    "did not supply that result. This is not a changed goal if it fully answers the original "
    "question under exactly its assumptions. Reject a candidate result assumed as a premise, "
    "an arbitrary witness or existence theorem in place of a requested value, missing "
    "completeness for all solutions/classification, missing attainment/global bound for an "
    "optimum, or unsupported numerical precision. Check the result against the original "
    "objects and domain, not merely the generator's restatement. For a whether question, "
    "the proved claim supports a yes answer and a proved negation supports a no answer; "
    "check that the explanation's yes/no conclusion matches the verified target. "
)

ANSWER_PRESENTATION = (
    "When the request asks to compute, solve or determine, give the explicit value, solution "
    "set or classification established by the verified target, followed by its mathematical "
    "derivation and completeness justification when required. Do not present only 'there "
    "exists an answer' or ask the learner to supply the result. State only results actually "
    "supported by the verified source; never fill a missing result by guessing. "
    "For a whether question, state yes or no and justify it using the verified claim "
    "or its verified negation; do not equate a proposed statement with a hypothesis. "
)

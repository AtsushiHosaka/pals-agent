import Lake
open Lake DSL

package «palsStacksWorkspace» where

-- Mathlib is required directly (same commit as the Stacks pin) so that `lake exe cache get`
-- resolves its cache executable from the root package.
require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @
    "56a005855ea17e0b0958f73ec801ae140b0a1679"

-- Only the reviewed `StacksCore` library is ever built from this package. `StacksFrontier` is
-- AI-generated and unreviewed; its sources are removed after fetching (see
-- docker/lean-verifier-stacks.Dockerfile) and `Stacks` (which imports it) is never built.
require Stacks from git
  "https://github.com/AxiomMath/Stacks.git" @
    "5ed82d14634e8d9576bb844c7bd4e3da66d450e7"

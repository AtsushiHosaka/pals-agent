module

public import StacksCore.Basic
import Mathlib.Hidden

-- import Mathlib.NotReal   (a comment is not an import)

namespace Frontier

public structure Thing where
  carrier : Type
  level : Nat

public def flatThing (T : Thing) : Nat := T.level

public theorem flatThing_self (T : Thing) : flatThing T = T.level := rfl

end Frontier

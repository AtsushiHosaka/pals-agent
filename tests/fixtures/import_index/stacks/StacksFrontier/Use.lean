module

public import StacksFrontier.Thing
public meta import Mathlib.Order
import all Mathlib.Algebra.Ring

namespace Frontier

public theorem use_thing (T : Frontier.Thing) : T.level = T.level := rfl

public theorem Thing.level_pos_iff (T : Frontier.Thing) : 0 < T.level ↔ 0 < T.level := Iff.rfl

end Frontier

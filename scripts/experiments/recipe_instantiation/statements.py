"""Hand-written statements for the Recipe-instantiation experiment (no model).

Each: id, kind, stmt (Lean type), G (designated Recipe, Lean name key), bind
(explicit args for the 'bound' closer or None), pool (key of the 5-candidate pool).
kind: def / nondef / at / comp / hyp / mono / diff / neg
"""
F = "fun x : ℝ => "
S = []
def add(i, kind, stmt, G, bind=None, pool="cont"):
    S.append(dict(id=i, kind=kind, stmt=stmt, G=G, bind=bind, pool=pool))

# --- definitional instances
add("P01_x2", "def", f"Continuous ({F}x ^ 2)", "pow_c", "2")
add("P02_x3", "def", f"Continuous ({F}x ^ 3)", "pow_c", "3")
add("P03_x5", "def", f"Continuous ({F}x ^ 5)", "pow_c", "5")
add("P04_3x", "def", f"Continuous ({F}3 * x)", "lin_c", "3")
add("P05_2x1", "def", f"Continuous ({F}2 * x + 1)", "aff_c", "2 1")
add("P06_0x5", "def", f"Continuous ({F}0 * x + 5)", "aff_c", "0 5")
add("P07_x2_sq", "def", f"Continuous ({F}x ^ 2)", "sq_c", "")
# --- not definitionally equal
add("P08_xx", "nondef", f"Continuous ({F}x * x)", "pow_c", "2")
add("P09_xm1", "nondef", f"Continuous ({F}x - 1)", "aff_c", "1 (-1)")
add("P10_x", "nondef", f"Continuous ({F}x)", "lin_c", "1")
add("P11_negx", "nondef", f"Continuous ({F}-x)", "lin_c", "(-1)")
add("P12_xdiv2", "nondef", f"Continuous ({F}x / 2)", "lin_c", "(1/2)")
add("P13_xxx", "nondef", f"Continuous ({F}x * x * x)", "pow_c", "3")
add("P14_xp1", "nondef", f"Continuous ({F}x + 1)", "aff_c", "1 1")
add("P15_2x_p_x", "nondef", f"Continuous ({F}2 * x + x)", "lin_c", "3")
# --- ContinuousAt from a Continuous Recipe
add("P16_at_x2", "at", f"ContinuousAt ({F}x ^ 2) 1", "pow_c", "2")
add("P17_at_3x", "at", f"ContinuousAt ({F}3 * x) 2", "lin_c", "3")
# --- compositions
add("P18_x2_p_3x1", "comp", f"Continuous ({F}x ^ 2 + (3 * x + 1))", "add_c")
add("P19_x2_3x_1", "comp", f"Continuous ({F}x ^ 2 + 3 * x + 1)", "add_c")
add("P20_x3_x2", "comp", f"Continuous ({F}x ^ 3 + x ^ 2)", "add_c")
add("P21_3x2", "comp", f"Continuous ({F}3 * x ^ 2)", "cmul_c")
add("P22_x2_plus_x", "comp", f"Continuous ({F}x ^ 2 + x)", "add_c")
add("P23_x2_1x", "comp", f"Continuous ({F}x ^ 2 + 1 * x)", "add_c")
add("P24_x2_x3_x4", "comp", f"Continuous ({F}x ^ 2 + x ^ 3 + x ^ 4)", "add_c")
add("P25_2x2_3x3", "comp", f"Continuous ({F}2 * x ^ 2 + 3 * x ^ 3)", "add_c")
# --- Recipes with hypotheses (abstract statements)
add("P26_add_abs", "hyp", "∀ f g : ℝ → ℝ, Continuous f → Continuous g → Continuous (fun x : ℝ => f x + g x)", "add_c")
add("P27_cmul_abs", "hyp", "∀ f : ℝ → ℝ, Continuous f → Continuous (fun x : ℝ => 3 * f x)", "cmul_c")
add("P28_ff", "hyp", "∀ f : ℝ → ℝ, Continuous f → Continuous (fun x : ℝ => f x + f x)", "add_c")
add("P29_x2_g", "hyp", "∀ g : ℝ → ℝ, Continuous g → Continuous (fun x : ℝ => x ^ 2 + g x)", "add_c")
# --- monotonicity
add("P31_mono_x3", "mono", f"StrictMono ({F}x ^ 3)", "odd_m", "1", "mono")
add("P32_mono_x5", "mono", f"StrictMono ({F}x ^ 5)", "odd_m", "2", "mono")
add("P33_mono_x7", "mono", f"StrictMono ({F}x ^ 7)", "odd_m", "3", "mono")
add("P34_mono_gen", "mono", "∀ n : ℕ, StrictMono (fun x : ℝ => x ^ (2 * n + 1))", "odd_m", "", "mono")
# --- differentiability
add("P35_d_x3", "diff", f"Differentiable ℝ ({F}x ^ 3)", "pow_d", "3", "diff")
add("P36_d_2x1", "diff", f"Differentiable ℝ ({F}2 * x + 1)", "aff_d", "2 1", "diff")
add("P37_d_3x", "diff", f"Differentiable ℝ ({F}3 * x)", "lin_d", "3", "diff")
add("P38_d_xx", "diff", f"Differentiable ℝ ({F}x * x)", "pow_d", "2", "diff")
add("P39_d_xm1", "diff", f"Differentiable ℝ ({F}x - 1)", "aff_d", "1 (-1)", "diff")
# --- negatives: must NOT be proved from these Recipes
add("N01_x2_p1", "neg", f"Continuous ({F}x ^ 2 + 1)", "pow_c", "2")
add("N02_inv", "neg", f"Continuous ({F}x⁻¹)", "pow_c", "1")
add("N03_mono_x2", "neg", f"StrictMono ({F}x ^ 2)", "odd_m", "1", "mono")
add("N04_abs_cont", "neg", f"Continuous ({F}|x|)", "pow_c", "1")
add("N05_abs_diff", "neg", f"Differentiable ℝ ({F}|x|)", "pow_d", "1", "diff")
add("N06_ucont_x2", "neg", f"UniformContinuous ({F}x ^ 2)", "lin_c", "1")
add("N07_x2x", "neg", f"Continuous ({F}x ^ 2 * x)", "pow_c", "3")
add("N08_mono_x4", "neg", f"StrictMono ({F}x ^ 4)", "odd_m", "1", "mono")
add("N09_step", "neg", f"Continuous ({F}if x < 0 then (0:ℝ) else 1)", "pow_c", "0")
add("N10_x2_p_inv", "neg", f"Continuous ({F}x ^ 2 + x⁻¹)", "add_c")

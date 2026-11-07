import Mathlib

theorem power_continuous_explicit_epsilon_delta :
    ∀ (n : ℕ), Continuous (fun x : ℝ => x ^ n) := by
  -- Key estimate: for |x - a| ≤ 1, |x^(m+1) - a^(m+1)| ≤ |x - a| * ((m+1) * (|a|+1)^m).
  have core : ∀ (m : ℕ) (x a : ℝ), |x - a| ≤ 1 →
      |x ^ (m + 1) - a ^ (m + 1)| ≤ |x - a| * ((m + 1) * (|a| + 1) ^ m) := by
    intro m x a h
    have hx : |x| ≤ |a| + 1 := by
      have h1 : |x| ≤ |a| + |x - a| := by
        calc |x| = |a + (x - a)| := by ring_nf
          _ ≤ |a| + |x - a| := abs_add_le _ _
      linarith
    have hM : 0 ≤ |a| + 1 := by positivity
    induction m with
    | zero => simp
    | succ k ih =>
      have key : x ^ (k + 1 + 1) - a ^ (k + 1 + 1)
          = x * (x ^ (k + 1) - a ^ (k + 1)) + a ^ (k + 1) * (x - a) := by ring
      rw [key]
      have h1 : |x * (x ^ (k + 1) - a ^ (k + 1))|
          ≤ (|a| + 1) * (|x - a| * ((k + 1) * (|a| + 1) ^ k)) := by
        rw [abs_mul]
        exact mul_le_mul hx ih (abs_nonneg _) hM
      have h2 : |a ^ (k + 1) * (x - a)| ≤ (|a| + 1) ^ (k + 1) * |x - a| := by
        rw [abs_mul, abs_pow]
        exact mul_le_mul_of_nonneg_right
          (pow_le_pow_left₀ (abs_nonneg a) (by linarith) _) (abs_nonneg _)
      calc |x * (x ^ (k + 1) - a ^ (k + 1)) + a ^ (k + 1) * (x - a)|
          ≤ |x * (x ^ (k + 1) - a ^ (k + 1))| + |a ^ (k + 1) * (x - a)| := abs_add_le _ _
        _ ≤ (|a| + 1) * (|x - a| * ((k + 1) * (|a| + 1) ^ k))
            + (|a| + 1) ^ (k + 1) * |x - a| := add_le_add h1 h2
        _ = |x - a| * (((k + 1 : ℕ) + 1 : ℝ) * (|a| + 1) ^ (k + 1)) := by
            push_cast; ring
  intro n
  rw [continuous_iff_continuousAt]
  intro a
  rw [Metric.continuousAt_iff]
  intro ε hε
  -- C = n * (|a|+1)^(n-1) + 1 > 0, and δ = min 1 (ε / C).
  set C : ℝ := n * (|a| + 1) ^ (n - 1) + 1 with hC
  have hCpos : 0 < C := by positivity
  refine ⟨min 1 (ε / C), lt_min one_pos (div_pos hε hCpos), ?_⟩
  intro x hx
  rw [Real.dist_eq] at hx ⊢
  have hx1 : |x - a| < 1 := lt_of_lt_of_le hx (min_le_left _ _)
  have hx2 : |x - a| < ε / C := lt_of_lt_of_le hx (min_le_right _ _)
  have h3 : |x ^ n - a ^ n| ≤ |x - a| * (n * (|a| + 1) ^ (n - 1)) := by
    cases n with
    | zero => simp
    | succ k =>
      have := core k x a hx1.le
      simpa using this
  have h4 : (n : ℝ) * (|a| + 1) ^ (n - 1) ≤ C := by rw [hC]; linarith
  have h5 : |x - a| * C < ε := (lt_div_iff₀ hCpos).mp hx2
  calc |x ^ n - a ^ n| ≤ |x - a| * (n * (|a| + 1) ^ (n - 1)) := h3
    _ ≤ |x - a| * C := mul_le_mul_of_nonneg_left h4 (abs_nonneg _)
    _ < ε := h5

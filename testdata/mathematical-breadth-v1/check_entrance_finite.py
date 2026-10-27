"""Exact finite supplements for the authored entrance cases, not completeness proofs."""

from fractions import Fraction
from itertools import combinations
from math import comb


def catalan(n: int) -> int:
    return comb(2 * n, n) // (n + 1)


def check_ballot() -> None:
    for n in range(1, 8):
        admitted = []
        all_ties = []
        for reds in combinations(range(2 * n), n):
            red_positions = set(reds)
            balance = 0
            nonnegative = True
            ties = []
            for i in range(2 * n):
                balance += 1 if i in red_positions else -1
                nonnegative &= balance >= 0
                if balance == 0:
                    ties.append((i + 1) // 2)
            all_ties.append(len(ties))
            if nonnegative:
                admitted.append(ties)
        assert len(admitted) == catalan(n)
        for k in range(1, n + 1):
            observed = sum(ties[0] == k for ties in admitted)
            assert observed == catalan(k - 1) * catalan(n - k)
        assert Fraction(sum(map(len, admitted)), len(admitted)) == Fraction(3 * n, n + 2)
        if n == 2:
            assert Fraction(sum(all_ties), len(all_ties)) == Fraction(5, 3)
    print("Ballot: exact enumeration n=1..7 agrees; unconditioned n=2 disproves altered claim.")


def check_descent() -> None:
    bound = 1000
    found = {
        (a, b)
        for a in range(1, bound + 1)
        for b in range(a, bound + 1)
        if a * a + b * b + 1 == 3 * a * b
    }
    sequence = [1, 1]
    while sequence[-1] <= bound:
        sequence.append(3 * sequence[-1] - sequence[-2])
    expected = {(a, b) for a, b in zip(sequence, sequence[1:], strict=False) if b <= bound}
    assert found == expected
    for a, b in found:
        if a > 1:
            smaller = 3 * a - b
            assert 0 < smaller < a
            assert smaller * smaller + a * a + 1 == 3 * smaller * a
    assert (-1) ** 2 + (-1) ** 2 + 1 == 3 * (-1) * (-1)
    assert 2 * 2 + 2 * 2 + 4 == 3 * 2 * 2
    print("Descent: bounded pairs through 1000 agree; altered-domain/constants negatives checked.")


if __name__ == "__main__":
    check_ballot()
    check_descent()
    print("Finite supplements passed; they do not prove Lean verification or completeness.")

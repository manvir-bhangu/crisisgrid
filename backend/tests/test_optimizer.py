import itertools

import numpy as np

from app.allocation.optimizer import UNREACHABLE, hungarian

BIG = UNREACHABLE + 1.0


def objective(T, w, plan):
    return sum(w[j] * (T[i][j] - BIG) for j, i in plan.items())


def brute_best(T, w):
    n_units, n_inc = len(T), len(T[0])
    k = min(n_units, n_inc)
    best = float("inf")
    for cols in itertools.combinations(range(n_inc), k):
        for rows in itertools.permutations(range(n_units), k):
            c = sum(w[j] * (T[i][j] - BIG) for i, j in zip(rows, cols))
            best = min(best, c)
    return best


def test_hungarian_matches_brute_force():
    rng = np.random.default_rng(1)
    for _ in range(200):
        n_units, n_inc = int(rng.integers(2, 6)), int(rng.integers(2, 6))
        T = rng.uniform(30, 900, size=(n_units, n_inc)).tolist()
        w = rng.choice([1, 2, 4, 8], size=n_inc).tolist()
        plan = hungarian(T, w)
        assert len(plan) == min(n_units, n_inc)
        assert abs(objective(T, w, plan) - brute_best(T, w)) < 1e-6


def test_critical_incident_wins_the_only_unit_even_if_farther():
    T = [[100.0, 500.0]]          # one unit, two incidents; incident 1 is farther
    assert hungarian(T, [1, 8]) == {1: 0}


def test_unreachable_pairs_are_never_assigned():
    T = [[float("nan"), 200.0]]
    assert hungarian(T, [1, 1]) == {1: 0}
"""Assignment algorithms over a travel-time matrix.
T[i][j] = seconds for unit i to reach incident j (NaN / inf = unreachable)."""
import numpy as np
from scipy.optimize import linear_sum_assignment

UNREACHABLE = 1e5  # seconds; anything at or above this means "cannot reach"


def clean(T) -> np.ndarray:
    A = np.array(T, dtype=float)
    A[~np.isfinite(A)] = UNREACHABLE
    return A


def greedy(T, order) -> dict[int, int]:
    """Process incidents in the given order; each takes the fastest still-free unit.
    Returns {incident index: unit index}."""
    A = clean(T)
    free = set(range(A.shape[0]))
    out: dict[int, int] = {}
    for j in order:
        if not free:
            break
        i = min(free, key=lambda u: A[u, j])
        if A[i, j] >= UNREACHABLE:
            continue
        out[j] = i
        free.discard(i)
    return out


def hungarian(T, weights) -> dict[int, int]:
    """Optimal one-to-one assignment minimising sum of weight[j] * time[i, j].

    The per-incident constant `big` matters when there are fewer units than
    incidents: without it, leaving an incident unserved would cost nothing, and the
    solver would drop the far-away critical ones. Subtracting `big` makes every
    served incident a gain proportional to its weight, so high-priority incidents
    are served first, then total weighted time is minimised."""
    A = clean(T)
    w = np.asarray(weights, dtype=float)
    big = UNREACHABLE + 1.0
    cost = w[None, :] * (A - big)
    rows, cols = linear_sum_assignment(cost)
    return {int(j): int(i) for i, j in zip(rows, cols) if A[i, j] < UNREACHABLE}
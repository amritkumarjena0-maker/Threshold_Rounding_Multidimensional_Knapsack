
from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog


@dataclass
class KnapsackResult:
    selected: list
    objective: float
    resource_usage: np.ndarray
    fractional_solution: np.ndarray
    lp_objective: float


class ThresholdRoundingKnapsack:
    """
    Threshold rounding for the multidimensional 0/1 Knapsack problem.

    Maximize:    sum(value[i] * x[i])
    Subject to:  sum(weight[i, j] * x[i]) <= capacity[j]
                 x[i] in {0, 1}

    LP relaxation permits 0 <= x[i] <= 1.
    """

    def __init__(self, values, weights, capacities, threshold=0.5):
        self.values = np.asarray(values, dtype=float)
        self.weights = np.asarray(weights, dtype=float)
        self.capacities = np.asarray(capacities, dtype=float)
        self.threshold = float(threshold)

        if self.values.ndim != 1 or self.values.size == 0:
            raise ValueError("Values must be a nonempty 1D array.")

        if self.weights.ndim != 2:
            raise ValueError("Weights must be a 2D matrix.")

        n = len(self.values)
        if self.weights.shape[0] != n:
            raise ValueError("Each item must have a weight row.")

        if self.weights.shape[1] != len(self.capacities):
            raise ValueError("Capacity count must match weight columns.")

        if np.any(self.values < 0):
            raise ValueError("Values must be nonnegative.")

        if np.any(self.weights < 0) or np.any(self.capacities < 0):
            raise ValueError("Weights and capacities must be nonnegative.")

        if not 0 < self.threshold <= 1:
            raise ValueError("Threshold must be in (0, 1].")

        if np.any(np.all(self.weights == 0, axis=1) & (self.values > 0)):
            # Such items are valid and will be selected automatically.
            pass

    def solve_lp_relaxation(self):
        """Solve the fractional LP relaxation."""

        result = linprog(
            c=-self.values,
            A_ub=self.weights.T,
            b_ub=self.capacities,
            bounds=[(0, 1)] * len(self.values),
            method="highs",
        )

        if not result.success:
            raise RuntimeError(
                f"LP solver failed: {result.message}"
            )

        return result.x, -result.fun

    def usage(self, selected):
        """Calculate usage of every resource."""
        return self.weights.T @ np.asarray(selected, dtype=float)

    def is_feasible(self, selected, tolerance=1e-9):
        """Check all capacity constraints."""
        return np.all(
            self.usage(selected) <= self.capacities + tolerance
        )

    def threshold_round(self, x):
        """
        Round fractional variables using the threshold.
        Items with x[i] >= threshold are initially selected.
        """
        selected = (x >= self.threshold).astype(int)

        # Zero-weight profitable items can always be selected.
        free_items = np.all(self.weights == 0, axis=1)
        selected[free_items & (self.values > 0)] = 1

        return selected

    def repair_feasibility(self, selected, x):
        """
        Remove items until every capacity constraint is satisfied.

        Removal priority uses value, fractional LP support, and
        normalized contribution to currently violated resources.
        """
        selected = selected.copy()
        eps = 1e-12

        while not self.is_feasible(selected):
            current_usage = self.usage(selected)
            overloaded = current_usage > self.capacities + eps

            candidates = np.flatnonzero(selected)
            if len(candidates) == 0:
                break

            # Normalize overload contributions by capacity.
            # For zero-capacity resources, use absolute weight.
            scale = np.where(
                self.capacities > eps,
                self.capacities,
                1.0,
            )

            scores = []
            for i in candidates:
                contribution = np.sum(
                    self.weights[i, overloaded] /
                    scale[overloaded]
                )

                # A selected item should contribute to an overload.
                # The fallback ensures progress for numerical edge cases.
                if contribution <= eps:
                    contribution = eps

                # Lower score means a better removal candidate.
                score = (
                    self.values[i]
                    * max(x[i], eps)
                    / contribution
                )
                scores.append((score, i))

            _, remove_item = min(scores)
            selected[remove_item] = 0

        return selected

    def greedy_augment(self, selected, x):
        """
        Try adding remaining items in descending value-per-resource
        order, while preserving every capacity constraint.
        """
        selected = selected.copy()
        remaining = np.flatnonzero(selected == 0)

        def priority(i):
            positive_caps = np.maximum(self.capacities, 1.0)
            normalized_weight = np.sum(
                self.weights[i] / positive_caps
            )

            if normalized_weight <= 1e-12:
                return float("inf")

            # Fractional LP value is used as a tie-breaker.
            return (
                self.values[i] / normalized_weight
                + 1e-9 * x[i]
            )

        remaining = sorted(
            remaining, key=priority, reverse=True
        )

        for i in remaining:
            trial = selected.copy()
            trial[i] = 1

            if self.is_feasible(trial):
                selected = trial

        return selected

    def solve(self):
        """Execute the complete threshold-rounding pipeline."""

        x, lp_objective = self.solve_lp_relaxation()

        selected = self.threshold_round(x)
        selected = self.repair_feasibility(selected, x)
        selected = self.greedy_augment(selected, x)

        objective = float(self.values @ selected)
        resource_usage = self.usage(selected)

        return KnapsackResult(
            selected=selected.tolist(),
            objective=objective,
            resource_usage=resource_usage,
            fractional_solution=x,
            lp_objective=float(lp_objective),
        )


def main():
    # Five items and three independent resource constraints.
    values = [20, 30, 35, 12, 25]

    # Columns represent weight, time, and energy.
    weights = [
        [2, 3, 2],
        [3, 2, 4],
        [4, 4, 3],
        [1, 2, 1],
        [2, 3, 3],
    ]

    capacities = [7, 8, 7]
    threshold = 0.5

    solver = ThresholdRoundingKnapsack(
        values=values,
        weights=weights,
        capacities=capacities,
        threshold=threshold,
    )

    result = solver.solve()

    print("=" * 65)
    print(" THRESHOLD ROUNDING: MULTIDIMENSIONAL KNAPSACK")
    print("=" * 65)

    print(f"\nThreshold: {threshold:.2f}")
    print(f"Number of items: {len(values)}")
    print(f"Number of constraints: {len(capacities)}")

    print("\nFractional LP solution:")
    for i, fraction in enumerate(result.fractional_solution):
        print(
            f"  Item {i + 1}: x = {fraction:.4f}, "
            f"value = {values[i]}"
        )

    print("\nRounded 0/1 solution:")
    for i, chosen in enumerate(result.selected):
        print(
            f"  Item {i + 1}: "
            f"{'SELECTED' if chosen else 'NOT SELECTED'}"
        )

    print("\nResource utilization:")
    names = ["Weight", "Time", "Energy"]

    for j, name in enumerate(names):
        used = result.resource_usage[j]
        cap = capacities[j]
        percentage = 100 * used / cap if cap else 0.0

        print(
            f"  {name:8s}: {used:.2f} / {cap:.2f} "
            f"({percentage:.1f}%)"
        )

    print("\nObjective comparison:")
    print(f"  Rounded integer value : {result.objective:.2f}")
    print(f"  Fractional LP upper bound: {result.lp_objective:.2f}")

    if result.lp_objective > 1e-12:
        ratio = result.objective / result.lp_objective
        print(f"  LP-relative value ratio: {ratio:.4f}")
    else:
        print("  LP-relative value ratio: undefined (zero LP value)")

    print(
        "\nFeasible:",
        solver.is_feasible(result.selected),
    )
    print("=" * 65)


if __name__ == "__main__":
    main()

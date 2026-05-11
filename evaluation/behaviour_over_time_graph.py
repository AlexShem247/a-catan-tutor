import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt

NUM_BINS = 10
CSV_PATH = Path("behaviour_over_time.csv")


def _bin_index(progress: float) -> int:
    if progress <= 0.0:
        return 0
    if progress >= 1.0:
        return NUM_BINS
    return min(int(round(progress * NUM_BINS)), NUM_BINS)


def load_binned_action_percentages(csv_path: Path):
    action_counts_by_bin = [defaultdict(int) for _ in range(NUM_BINS + 1)]
    total_counts_by_bin = [0 for _ in range(NUM_BINS + 1)]
    action_types = set()

    with csv_path.open("r", newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            progress = float(row["progress"])
            action_type = row["action_type"].strip()
            bin_index = _bin_index(progress)

            action_counts_by_bin[bin_index][action_type] += 1
            total_counts_by_bin[bin_index] += 1
            action_types.add(action_type)

    ordered_action_types = sorted(action_types)
    percentages_by_action = {action_type: [] for action_type in ordered_action_types}

    for bin_index in range(NUM_BINS + 1):
        total_count = total_counts_by_bin[bin_index]
        for action_type in ordered_action_types:
            action_count = action_counts_by_bin[bin_index][action_type]
            percentage = (100.0 * action_count / total_count) if total_count > 0 else 0.0
            percentages_by_action[action_type].append(percentage)

    return ordered_action_types, percentages_by_action


def plot_behaviour_over_time(csv_path: Path) -> None:
    action_types, percentages_by_action = load_binned_action_percentages(csv_path)

    x_values = [(index / NUM_BINS) * 100.0 for index in range(NUM_BINS + 1)]

    plt.figure(figsize=(10, 6))
    for action_type in action_types:
        legend_label = action_type.replace("_", " ").title()
        plt.plot(x_values, percentages_by_action[action_type], marker="o", markersize=4, label=legend_label)

    plt.xlim(0, 100)
    plt.ylim(0, 100)
    tick_values = [index * (100 / NUM_BINS) for index in range(NUM_BINS + 1)]
    plt.xticks(
        tick_values,
        [f"{tick_value:.0f}%" for tick_value in tick_values],
    )
    plt.xlabel("Game Progression (%)")
    plt.ylabel("Percentage of Tutor Recommendations")
    plt.title("Tutor Recommendations Across Game Progression")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    plot_behaviour_over_time(CSV_PATH)

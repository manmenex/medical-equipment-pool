"""Small matplotlib-in-Qt chart widgets used on the Dashboard (FUNCTION 7)."""

from __future__ import annotations

from collections import Counter

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class ChartCanvas(FigureCanvas):
    """A matplotlib canvas pre-styled to match the app's dark/light theme."""

    def __init__(self, title: str = "", dark: bool = True, parent=None):
        self.dark = dark
        fig = Figure(figsize=(4, 3), tight_layout=True)
        super().__init__(fig)
        self.setParent(parent)
        self.axes = fig.add_subplot(111)
        self.title = title
        self._apply_palette()

    def _apply_palette(self) -> None:
        bg = "#161B22" if self.dark else "#FFFFFF"
        fg = "#E6EDF3" if self.dark else "#1B2430"
        self.figure.patch.set_facecolor(bg)
        self.axes.set_facecolor(bg)
        for spine in self.axes.spines.values():
            spine.set_color(fg)
        self.axes.tick_params(colors=fg, labelsize=8)
        self.axes.title.set_color(fg)
        self.axes.xaxis.label.set_color(fg)
        self.axes.yaxis.label.set_color(fg)

    def plot_bar_counts(self, labels: list[str], values: list[int], color: str = "#0FB5AE") -> None:
        self.axes.clear()
        self._apply_palette()
        self.axes.bar(labels, values, color=color)
        self.axes.set_title(self.title)
        self.axes.tick_params(axis="x", rotation=30)
        self.draw()

    def plot_pie(self, labels: list[str], values: list[int], colors: list[str]) -> None:
        self.axes.clear()
        self._apply_palette()
        if sum(values) == 0:
            self.axes.text(0.5, 0.5, "No data", ha="center", va="center")
        else:
            self.axes.pie(values, labels=labels, colors=colors, autopct="%1.0f%%", textprops={"fontsize": 8})
        self.axes.set_title(self.title)
        self.draw()


def top_n_counter(values: list[str], n: int = 8) -> tuple[list[str], list[int]]:
    """Return the top-N most common non-empty values and their counts."""
    counts = Counter(v for v in values if v)
    most_common = counts.most_common(n)
    if not most_common:
        return [], []
    labels, freq = zip(*most_common)
    return list(labels), list(freq)

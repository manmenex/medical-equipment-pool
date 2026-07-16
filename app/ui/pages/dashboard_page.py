"""Dashboard page (FUNCTION 7)."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.services.app_context import AppContext
from app.ui.widgets.charts import ChartCanvas, top_n_counter
from app.ui.widgets.stat_card import StatCard


class DashboardPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self.is_dark = context.settings.ui_theme.lower() == "dark"

        outer = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        outer.addLayout(header)

        # -- stat cards -------------------------------------------------------
        self.card_today = StatCard("Today's Date")
        self.card_last_update = StatCard("Last Update")
        self.card_fda = StatCard("FDA Records")
        self.card_ecri = StatCard("ECRI Records")
        self.card_inventory = StatCard("Inventory Records")
        self.card_matched = StatCard("Matched Devices")
        self.card_possible = StatCard("Possible Matches")
        self.card_latest_recall = StatCard("Latest Recall")

        cards_grid = QGridLayout()
        cards = [
            self.card_today, self.card_last_update, self.card_fda, self.card_ecri,
            self.card_inventory, self.card_matched, self.card_possible, self.card_latest_recall,
        ]
        for i, card in enumerate(cards):
            cards_grid.addWidget(card, i // 4, i % 4)
        outer.addLayout(cards_grid)

        # -- charts -------------------------------------------------------------
        charts_layout = QHBoxLayout()
        self.chart_manufacturer = ChartCanvas("Recalls by Manufacturer", dark=self.is_dark)
        self.chart_by_month = ChartCanvas("Recalls by Month", dark=self.is_dark)
        self.chart_by_class = ChartCanvas("Recall Class Distribution", dark=self.is_dark)
        charts_layout.addWidget(self.chart_manufacturer)
        charts_layout.addWidget(self.chart_by_month)
        charts_layout.addWidget(self.chart_by_class)
        outer.addLayout(charts_layout, stretch=1)

        self.refresh()

    def refresh(self) -> None:
        ctx = self.context
        self.card_today.set_value(date.today().strftime("%Y-%m-%d"))

        last_update_row = ctx.db.query_one("SELECT value FROM app_settings WHERE key = 'last_update'")
        self.card_last_update.set_value(
            datetime.fromisoformat(last_update_row["value"]).strftime("%Y-%m-%d %H:%M")
            if last_update_row
            else "Never"
        )

        fda_recalls = ctx.fda_service.list_all()
        ecri_alerts = ctx.ecri_service.list_all()
        self.card_fda.set_value(str(len(fda_recalls)))
        self.card_ecri.set_value(str(len(ecri_alerts)))
        self.card_inventory.set_value(str(ctx.inventory_service.count()))

        match_counts = ctx.match_repository.counts_summary()
        self.card_matched.set_value(str(match_counts.get("Matched", 0)))
        self.card_possible.set_value(str(match_counts.get("Possible Match", 0)))

        if fda_recalls:
            latest = max(fda_recalls, key=lambda r: r.date_initiated or date.min)
            self.card_latest_recall.set_value(latest.recall_number)
        else:
            self.card_latest_recall.set_value("-")

        manufacturers = [r.manufacturer for r in fda_recalls] + [a.manufacturer for a in ecri_alerts]
        labels, values = top_n_counter(manufacturers)
        self.chart_manufacturer.plot_bar_counts(labels, values)

        month_counts = Counter(
            r.date_initiated.strftime("%Y-%m") for r in fda_recalls if r.date_initiated
        )
        months_sorted = sorted(month_counts.keys())[-12:]
        self.chart_by_month.plot_bar_counts(months_sorted, [month_counts[m] for m in months_sorted])

        class_counts = Counter(r.recall_class for r in fda_recalls if r.recall_class)
        self.chart_by_class.plot_pie(
            list(class_counts.keys()),
            list(class_counts.values()),
            colors=["#E5484D", "#F5A524", "#12B76A", "#1F6FEB"][: len(class_counts)],
        )

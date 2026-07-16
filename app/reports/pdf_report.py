"""PDF report renderer (FUNCTION 6), built with ReportLab's Platypus layer
so long detail tables paginate automatically."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.report_data import ReportData
from app.utils.exceptions import ReportGenerationError
from app.utils.logging_config import get_audit_logger, get_logger

logger = get_logger(__name__)
audit_export = get_audit_logger("export")

_HEADER_COLOR = colors.HexColor("#1F4E78")


def _table(headers: list[str], rows: list[list[str]], col_widths=None) -> Table:
    data = [headers] + rows
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_COLOR),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def generate_pdf_report(data: ReportData, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=20)
        heading_style = ParagraphStyle("HeadingStyle", parent=styles["Heading2"], spaceBefore=16)

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=landscape(letter),
            leftMargin=0.5 * inch,
            rightMargin=0.5 * inch,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            title=f"Recall Report {data.period.label}",
        )

        story = [
            Paragraph("Medical Device Recall Report", title_style),
            Paragraph(
                f"Period: {data.period.label} ({data.period.start_date} to {data.period.end_date})",
                styles["Normal"],
            ),
            Spacer(1, 12),
            Paragraph("Summary", heading_style),
            _table(
                ["Metric", "Count"],
                [
                    ["Total FDA Recalls", str(data.total_fda)],
                    ["Total ECRI Alerts", str(data.total_ecri)],
                    ["Hospital Matches", str(data.total_matched)],
                    ["Possible Matches", str(data.total_possible)],
                    ["No Match", str(data.total_not_matched)],
                ],
                col_widths=[3 * inch, 1.5 * inch],
            ),
            Spacer(1, 16),
        ]

        if data.match_results:
            story.append(Paragraph("Match Detail", heading_style))
            story.append(
                _table(
                    ["Source", "Recall #", "Asset #", "Manufacturer", "Model", "Score", "Status", "Method"],
                    [
                        [
                            m.recall_source.value,
                            m.recall_number,
                            m.hospital_asset_number,
                            m.manufacturer,
                            m.model,
                            f"{m.confidence_score:.0f}%",
                            m.status.value,
                            m.method.value,
                        ]
                        for m in data.match_results
                    ],
                )
            )
            story.append(Spacer(1, 16))

        if data.fda_recalls:
            story.append(Paragraph("FDA Recalls", heading_style))
            story.append(
                _table(
                    ["Recall #", "Class", "Product", "Manufacturer", "Reason", "Date Initiated", "Status"],
                    [
                        [
                            r.recall_number,
                            r.recall_class,
                            r.product[:60],
                            r.manufacturer[:30],
                            r.reason[:60],
                            r.date_initiated.isoformat() if r.date_initiated else "",
                            r.status,
                        ]
                        for r in data.fda_recalls
                    ],
                )
            )
            story.append(Spacer(1, 16))

        if data.ecri_alerts:
            story.append(Paragraph("ECRI Alerts", heading_style))
            story.append(
                _table(
                    ["Alert #", "Title", "Manufacturer", "Model", "Hazard", "Date Issued", "Status"],
                    [
                        [
                            a.alert_number,
                            a.title[:60],
                            a.manufacturer[:30],
                            a.model_number,
                            a.hazard_level,
                            a.date_issued.isoformat() if a.date_issued else "",
                            a.status,
                        ]
                        for a in data.ecri_alerts
                    ],
                )
            )

        doc.build(story)
    except Exception as exc:
        raise ReportGenerationError(f"Failed to generate PDF report: {exc}") from exc

    audit_export.info("PDF report generated: %s", output_path)
    return output_path

from app.models.enums import MatchMethod, MatchStatus, RecallSource
from app.models.match import MatchResult
from app.models.recall import FDARecall
from app.models.report_data import ReportData
from app.reports.excel_report import generate_excel_report
from app.reports.pdf_report import generate_pdf_report
from app.services.period_service import get_period


def _sample_report_data():
    period = get_period(2026, 7, 2)
    fda = [FDARecall(recall_number="R-1", manufacturer="Acme", product="Pump")]
    match = [
        MatchResult(
            recall_source=RecallSource.FDA,
            recall_number="R-1",
            hospital_asset_number="A-1",
            manufacturer="Acme",
            model="IP-3000",
            confidence_score=100.0,
            status=MatchStatus.MATCHED,
            method=MatchMethod.UDI,
        )
    ]
    return ReportData(period=period, fda_recalls=fda, ecri_alerts=[], match_results=match)


def test_report_filename_convention(tmp_path):
    data = _sample_report_data()
    expected_name = f"Recall_Report_{data.period.label}"
    assert expected_name == "Recall_Report_2026_Week2"

    excel_path = generate_excel_report(data, tmp_path / f"{expected_name}.xlsx")
    pdf_path = generate_pdf_report(data, tmp_path / f"{expected_name}.pdf")

    assert excel_path.exists()
    assert pdf_path.exists()
    assert excel_path.name == "Recall_Report_2026_Week2.xlsx"
    assert pdf_path.name == "Recall_Report_2026_Week2.pdf"


def test_report_data_summary_counts():
    data = _sample_report_data()
    assert data.total_fda == 1
    assert data.total_matched == 1
    assert data.total_possible == 0
    assert data.total_not_matched == 0

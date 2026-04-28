from __future__ import annotations

from pathlib import Path

from core.models import TestResult
from core.result_summary import SummaryResult


RAW_HEADERS = [
    "序号",
    "制式",
    "Band",
    "信道",
    "频点类型",
    "测试模式",
    "接收电平(dBm)",
    "指标类型",
    "指标值",
    "结果",
    "状态",
    "时间",
]

SUMMARY_HEADERS = [
    "制式",
    "Band",
    "信道",
    "频点类型",
    "测试模式",
    "灵敏度(dBm)",
    "PASS数量",
    "FAIL数量",
    "总数",
    "结果",
    "备注",
]


def export_results_to_excel(
    raw_results: list[TestResult],
    summary_results: list[SummaryResult],
    file_path: str,
) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    raw_sheet = workbook.active
    raw_sheet.title = "RawResults"
    summary_sheet = workbook.create_sheet("Summary")

    fills = {
        "PASS": PatternFill("solid", fgColor="EAF7EA"),
        "FAIL": PatternFill("solid", fgColor="FDECEC"),
    }
    header_fill = PatternFill("solid", fgColor="E5EBF0")
    header_font = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")

    _write_sheet(
        raw_sheet,
        RAW_HEADERS,
        [_raw_result_row(result) for result in raw_results],
        fills,
        header_fill,
        header_font,
        center,
        result_column_name="结果",
    )
    _write_sheet(
        summary_sheet,
        SUMMARY_HEADERS,
        [_summary_result_row(result) for result in summary_results],
        fills,
        header_fill,
        header_font,
        center,
        result_column_name="结果",
    )

    output_path = Path(file_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def _write_sheet(
    sheet,
    headers: list[str],
    rows: list[list[object]],
    fills: dict[str, object],
    header_fill,
    header_font,
    center,
    result_column_name: str,
) -> None:
    sheet.append(headers)
    for row in rows:
        sheet.append(row)

    result_column_index = headers.index(result_column_name) + 1
    for cell in sheet[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center

    for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
        result_value = str(row[result_column_index - 1].value or "").upper()
        row_fill = fills.get(result_value)
        for cell in row:
            cell.alignment = center
            if row_fill:
                cell.fill = row_fill

    sheet.freeze_panes = "A2"
    _auto_fit_columns(sheet)


def _auto_fit_columns(sheet) -> None:
    for column_cells in sheet.columns:
        max_length = 0
        column_letter = column_cells[0].column_letter
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        sheet.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 32)


def _raw_result_row(result: TestResult) -> list[object]:
    return [
        result.index,
        result.mode,
        result.band,
        result.channel,
        result.channel_type,
        result.test_mode,
        result.rx_level,
        result.metric_type,
        result.metric_value,
        result.result,
        result.status,
        result.timestamp,
    ]


def _summary_result_row(result: SummaryResult) -> list[object]:
    return [
        result.mode,
        result.band,
        result.channel,
        result.channel_type,
        result.test_mode,
        "-" if result.sensitivity is None else result.sensitivity,
        result.pass_count,
        result.fail_count,
        result.total_count,
        result.result,
        result.remark,
    ]

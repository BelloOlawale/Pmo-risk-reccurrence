"""Parse risk register Excel files — detect headers, extract rows as dicts."""

from __future__ import annotations

from typing import Any

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet


def parse_excel(filepath: str) -> list[dict[str, str]]:
    """Parse a risk register .xlsx file and return rows as dicts.

    Detects the header row by scanning for known risk register column keywords,
    then extracts all data rows below it. Handles zero-width characters and
    files with blank column A (like Seamless HR).

    Returns an empty list for unreadable files (corrupt, OLE2/.xls format, no data).
    """
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
    except Exception:
        return []

    ws = wb.active
    if ws is None:
        wb.close()
        return []

    header_row_idx = _find_header_row(ws)
    if header_row_idx is None:
        wb.close()
        return []

    headers = _extract_headers(ws, header_row_idx)
    rows = _extract_rows(ws, header_row_idx, headers)
    wb.close()
    return rows


def _clean(val: Any) -> str:
    """Convert cell value to string, stripping zero-width characters."""
    if val is None:
        return ""
    return (
        str(val)
        .strip()
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
    )


def _find_header_row(ws: Worksheet) -> int | None:
    """Find the header row index (1-based) by scanning for risk register keywords.

    Scores each row by counting keyword matches across all columns, then picks
    the best match. This handles files where metadata rows contain incidental
    keyword hits (e.g. "Impact (I): High, Medium, Low" in a description cell)
    while the real header row has multiple column headers with strong matches.
    """
    header_keywords = [
        "risk id", "risk description", "description of risk",
        "risk category", "probability", "likelihood",
        "impact", "mitigation", "response", "owner",
        "s/n", "risk score", "risk level", "risk owner",
        "risk rating", "status", "category",
    ]

    best_score = 0
    best_row: int | None = None

    for row_idx in range(1, min(ws.max_row + 1, 30)):
        # Score each cell independently against keywords
        score = 0
        for c in range(1, ws.max_column + 1):
            cell_text = _clean(ws.cell(row=row_idx, column=c).value).lower()
            if not cell_text:
                continue
            for kw in header_keywords:
                if kw in cell_text:
                    score += 1
        if score > best_score:
            best_score = score
            best_row = row_idx

    # Require at least 2 column matches to be a real header row
    return best_row if best_score >= 2 else None


def _extract_headers(ws: Worksheet, header_row_idx: int) -> list[str]:
    """Extract cleaned header names from the header row."""
    headers: list[str] = []
    for col in range(1, ws.max_column + 1):
        val = _clean(ws.cell(row=header_row_idx, column=col).value)
        if val:
            headers.append(val)
    return headers


def _extract_rows(
    ws: Worksheet, header_row_idx: int, headers: list[str]
) -> list[dict[str, str]]:
    """Extract data rows below the header, mapping to header names."""
    rows: list[dict[str, str]] = []
    empty_count = 0

    for row_idx in range(header_row_idx + 1, ws.max_row + 1):
        # Check if row has any data in first few columns
        has_data = False
        for c in range(1, min(ws.max_column + 1, 5)):
            val = _clean(ws.cell(row=row_idx, column=c).value)
            if val:
                has_data = True
                break

        if not has_data:
            empty_count += 1
            if empty_count >= 3:
                break  # Stop after 3 consecutive empty rows
            continue

        empty_count = 0

        # Build row dict, but offset column index by 1 if first column is blank
        # (handles Seamless HR pattern where column A is blank)
        first_col_blank = not _clean(ws.cell(row=row_idx, column=1).value)
        offset = 1 if first_col_blank else 0

        row: dict[str, str] = {}
        for i, header in enumerate(headers):
            col = i + 1 + offset
            if col <= ws.max_column:
                row[header] = _clean(ws.cell(row=row_idx, column=col).value)
            else:
                row[header] = ""
        rows.append(row)

    return rows

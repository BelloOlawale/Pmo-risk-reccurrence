"""Centralised product branding.

One source of truth for the user-facing product name so a rebrand never has to
hunt through templates, email bodies and workbook metadata. Technical module,
package and environment-variable names deliberately keep the historical
``riskapp`` prefix: they are not user-facing and renaming them would be a
risk-heavy, value-free change.

The brand lockup is rendered on two lines::

    PMO RISK
    INTELLIGENCE
"""

from __future__ import annotations

# Full product name (page titles, email subjects, workbook metadata).
PRODUCT_NAME = "PMO Risk Intelligence"

# Two-line brand lockup. The first line is deliberately lighter; the second is
# the prominent, bold element of the mark.
BRAND_LINE_1 = "PMO RISK"
BRAND_LINE_2 = "INTELLIGENCE"

# Wragby brand colours (mirrors frontend/src/utils/colors.ts and index.css).
BRAND_BLUE = "#173F6B"
BRAND_BLUE_DARK = "#102C4C"
BRAND_RED = "#ED1C2E"

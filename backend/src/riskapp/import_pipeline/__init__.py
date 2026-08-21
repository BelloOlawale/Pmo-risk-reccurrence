"""Historical data import pipeline (ported from the legacy app).

Pipeline: ``excel_parser`` → ``field_mapper`` → ``importer``.
"""

from riskapp.import_pipeline.importer import (
    ImportResult,
    SchemaType,
    detect_schema,
    import_directory,
)

__all__ = ["ImportResult", "SchemaType", "detect_schema", "import_directory"]

# Shared risk catalog (collapse risk concepts into single entries)

The risk library stores each risk concept once and reuses it across projects via
Project Risk instances, instead of one catalog row per source register. Chosen so
the suggestion engine queries a deduplicated catalog ("every risk tagged
category=vendor"); the trade-off is that per-source-file traceability moves from
the catalog down to the Project Risk instance.

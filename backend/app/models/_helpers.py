"""Helpers shared by the model modules."""


def sql_in_list(values: tuple[str, ...]) -> str:
    """Quoted, comma-separated literals for a CHECK constraint's `IN (...)`."""
    return ",".join(f"'{v}'" for v in values)

"""Give calls made before call numbers existed an id of the new form
("CALL-000123"), oldest first, everywhere a call is referred to.

A one-off, run by hand with the backend stopped (python -m app.cli
renumber-calls): a call written to while it is being renamed would be
split between its two ids. Everything happens in one transaction; a dry
run does the whole of it and rolls back.

Not renamed: a call with a stored recording or an off-server copy (their
files are filed under the old id), which keeps its id and is reported;
and ids that merely contain a call id (a transcript line's id), which
nothing reads the call's id out of.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, inspect, text

from app.domain.call_number import call_number, format_call_id
from app.infrastructure.database.repositories.call_numbers import CALL_NUMBER_SEQUENCE

# A row here is what children point at: it is copied under the new id,
# the children moved, then the old row removed (a key cannot be changed
# under rows that refer to it).
_PARENTS = ("conversations", "conversation_coverages")
# Calls with a row in one of these keep their id.
_FILED_UNDER_THE_ID = ("call_recordings", "transcript_archives")
# Lists of call ids kept as JSON: (table, key column, list column).
_ID_LISTS = (("emerging_complaint_candidates", "candidate_id", "call_ids"),)


@dataclass
class Renumbering:
    # old id -> new id, in the order the calls were made.
    renamed: dict[str, str] = field(default_factory=dict)
    # Calls left alone, with why.
    kept: dict[str, str] = field(default_factory=dict)
    # table.column -> rows changed.
    rows_changed: dict[str, int] = field(default_factory=dict)
    # Rows that still name an old id afterwards (expected: none).
    left_behind: int = 0
    applied: bool = False


def renumber_calls(engine: Engine, apply: bool = False) -> Renumbering:
    result = Renumbering()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _renumber(connection, result)
            if apply:
                transaction.commit()
                result.applied = True
            else:
                transaction.rollback()
        except BaseException:
            transaction.rollback()
            raise
    return result


def _renumber(connection: Connection, result: Renumbering) -> None:
    tables = set(inspect(connection).get_table_names())
    calls = connection.execute(
        text("SELECT call_id FROM conversations ORDER BY start_time, call_id")
    ).scalars().all()

    filed: dict[str, str] = {}
    for table in _FILED_UNDER_THE_ID:
        if table in tables:
            for call_id in connection.execute(text(f'SELECT call_id FROM "{table}"')).scalars():
                filed.setdefault(call_id, table)

    highest = max((call_number(call_id) or 0 for call_id in calls), default=0)
    for call_id in calls:
        if call_number(call_id) is not None:
            continue
        if call_id in filed:
            result.kept[call_id] = f"has a row in {filed[call_id]}"
            continue
        highest += 1
        result.renamed[call_id] = format_call_id(highest)

    if result.renamed:
        _rename_everywhere(connection, tables, result)
    # The next new call takes the number after the highest one in use.
    if highest and connection.dialect.name == "postgresql":
        connection.execute(
            text(f"SELECT setval('{CALL_NUMBER_SEQUENCE}', :highest)"), {"highest": highest}
        )
    result.left_behind = _still_named(connection, tables, list(result.renamed))


def _rename_everywhere(connection: Connection, tables: set[str], result: Renumbering) -> None:
    inspector = inspect(connection)
    connection.execute(text("CREATE TEMPORARY TABLE call_renames (old_id TEXT PRIMARY KEY, new_id TEXT NOT NULL)"))
    connection.execute(
        text("INSERT INTO call_renames (old_id, new_id) VALUES (:old, :new)"),
        [{"old": old, "new": new} for old, new in result.renamed.items()],
    )

    def changed(name: str, count: int) -> None:
        if count:
            result.rows_changed[name] = result.rows_changed.get(name, 0) + count

    # 1. The rows others point at, copied under the new id.
    for table in _PARENTS:
        if table not in tables:
            continue
        others = [c["name"] for c in inspector.get_columns(table) if c["name"] != "call_id"]
        names = ", ".join(["call_id", *(f'"{name}"' for name in others)])
        values = ", ".join(["r.new_id", *(f't."{name}"' for name in others)])
        copied = connection.execute(
            text(
                f'INSERT INTO "{table}" ({names}) '
                f'SELECT {values} FROM "{table}" t JOIN call_renames r ON r.old_id = t.call_id'
            )
        )
        changed(f"{table}.call_id", copied.rowcount)

    # 2. Everything else that names a call.
    for table in sorted(tables - set(_PARENTS)):
        for column in inspector.get_columns(table):
            name = column["name"]
            is_call = name == "call_id" or (table == "audit_log" and name == "target_id")
            if not is_call:
                continue
            only_calls = " AND target_type = 'call'" if name == "target_id" else ""
            updated = connection.execute(
                text(
                    f'UPDATE "{table}" SET "{name}" = (SELECT new_id FROM call_renames WHERE old_id = "{table}"."{name}") '
                    f'WHERE "{name}" IN (SELECT old_id FROM call_renames){only_calls}'
                )
            )
            changed(f"{table}.{name}", updated.rowcount)

    # 3. The old rows, now with nothing pointing at them.
    for table in reversed(_PARENTS):
        if table in tables:
            connection.execute(
                text(f'DELETE FROM "{table}" WHERE call_id IN (SELECT old_id FROM call_renames)')
            )

    # 4. Lists of call ids.
    for table, key, column in _ID_LISTS:
        if table not in tables:
            continue
        rows = connection.execute(text(f'SELECT "{key}", "{column}" FROM "{table}"')).all()
        for row_key, ids in rows:
            ids = json.loads(ids) if isinstance(ids, str) else ids
            if not ids or not any(call_id in result.renamed for call_id in ids):
                continue
            renamed = [result.renamed.get(call_id, call_id) for call_id in ids]
            value = "CAST(:ids AS JSON)" if connection.dialect.name == "postgresql" else ":ids"
            connection.execute(
                text(f'UPDATE "{table}" SET "{column}" = {value} WHERE "{key}" = :key'),
                {"ids": json.dumps(renamed), "key": row_key},
            )
            changed(f"{table}.{column}", 1)

    connection.execute(text("DROP TABLE call_renames"))


def _still_named(connection: Connection, tables: set[str], old_ids: list[str]) -> int:
    """Rows whose call column still holds an id that was renamed."""
    if not old_ids:
        return 0
    inspector = inspect(connection)
    left = 0
    for table in sorted(tables):
        for column in inspector.get_columns(table):
            if column["name"] != "call_id":
                continue
            for start in range(0, len(old_ids), 500):
                batch = old_ids[start : start + 500]
                marks = ", ".join(f":id{n}" for n in range(len(batch)))
                left += connection.execute(
                    text(f'SELECT count(*) FROM "{table}" WHERE call_id IN ({marks})'),
                    {f"id{n}": call_id for n, call_id in enumerate(batch)},
                ).scalar_one()
    return left

"""Small synchronous adapter for Cloudflare D1 used by Flask's WSGI routes."""

import sqlite3


class D1Row:
    def __init__(self, values):
        self._keys = list(values.keys())
        self._values = list(values.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._keys.index(key)]


class D1Cursor:
    def __init__(self, rows=None, changes=0, lastrowid=None):
        self._rows = rows or []
        self._index = 0
        self.rowcount = changes
        self.lastrowid = lastrowid

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        rows = self._rows[self._index:]
        self._index = len(self._rows)
        return rows


class _AttributeDict(dict):
    def __getattr__(self, name):
        return self[name]


class D1Connection:
    def __init__(self, database):
        self.database = database

    def execute(self, query, parameters=()):
        from pyodide.ffi import run_sync

        try:
            statement = self.database.prepare(query).bind(*parameters)
            if _returns_rows(query):
                result = run_sync(statement.all())
                raw_rows = _to_python(result.results)
                rows = [D1Row(row) for row in raw_rows]
                return D1Cursor(rows)
            result = run_sync(statement.run())
            metadata = result.meta
            return D1Cursor(
                changes=metadata.changes,
                lastrowid=getattr(metadata, "last_row_id", None),
            )
        except Exception as exc:
            message = str(exc)
            if any(marker in message.lower() for marker in (
                "unique constraint", "check constraint", "foreign key constraint"
            )):
                raise sqlite3.IntegrityError(message) from exc
            raise

    def batch(self, statements):
        from pyodide.ffi import run_sync

        prepared = [self.database.prepare(query).bind(*parameters)
                    for query, parameters in statements]
        results = _to_python(run_sync(self.database.batch(prepared)))
        return [_AttributeDict({
            **result,
            "meta": _AttributeDict(result["meta"]),
        }) for result in results]


def batch(connection, statements):
    """Run statements atomically; D1 rolls back the batch if any statement fails."""
    return connection.batch(statements)


def _returns_rows(query):
    normalized = query.lstrip().upper()
    return normalized.startswith(("SELECT", "PRAGMA", "WITH")) or " RETURNING " in normalized


def _to_python(value):
    return value.to_py() if hasattr(value, "to_py") else value

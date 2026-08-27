"""
Shim en memoria del subconjunto de la API de supabase-py que usan
`app/data/usuarios_repo.py` y `app/data/cuentas_config_repo.py`
(`.table().select().order().execute()`, `.insert().execute()`,
`.update().eq().execute()`, `.delete().eq()/.neq().execute()`,
`.select().ilike().limit().execute()`).

Se usa SOLO para la verificación local end-to-end (ver
`tests/run_verification.py`), sin necesidad de credenciales reales de
Supabase — no se usa en producción.
"""

import uuid
from types import SimpleNamespace


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self.rows = store.setdefault(name, [])
        self._filters = []
        self._order = None
        self._limit = None
        self._mode = None
        self._payload = None

    # filtros
    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def ilike(self, col, val):
        self._filters.append(("ilike", col, val))
        return self

    def order(self, col):
        self._order = col
        return self

    def limit(self, n):
        self._limit = n
        return self

    # operaciones
    def select(self, *_a, **_kw):
        self._mode = "select"
        return self

    def insert(self, payload):
        self._mode = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._mode = "update"
        self._payload = payload
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def _matches(self, row):
        for kind, col, val in self._filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "neq" and row.get(col) == val:
                return False
            if kind == "ilike" and str(row.get(col, "")).lower() != str(val).lower():
                return False
        return True

    def execute(self):
        if self._mode == "select":
            rows = [r for r in self.rows if self._matches(r)]
            if self._order:
                rows = sorted(rows, key=lambda r: r.get(self._order) or 0)
            if self._limit:
                rows = rows[: self._limit]
            return _Result([dict(r) for r in rows])

        if self._mode == "insert":
            payload = self._payload
            items = payload if isinstance(payload, list) else [payload]
            created = []
            for item in items:
                row = dict(item)
                row.setdefault("id", str(uuid.uuid4()))
                self.rows.append(row)
                created.append(dict(row))
            return _Result(created)

        if self._mode == "update":
            updated = []
            for row in self.rows:
                if self._matches(row):
                    row.update(self._payload)
                    updated.append(dict(row))
            return _Result(updated)

        if self._mode == "delete":
            keep = [r for r in self.rows if not self._matches(r)]
            removed = [r for r in self.rows if self._matches(r)]
            self.rows[:] = keep
            return _Result(removed)

        raise RuntimeError("Operación no soportada en FakeSupabase")


class FakeSupabase:
    def __init__(self):
        self._store = {}

    def table(self, name):
        return _Query(self._store, name)

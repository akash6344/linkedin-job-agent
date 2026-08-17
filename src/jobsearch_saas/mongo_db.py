"""MongoDB backend for LetItApply when MONGO_URI is set.

Provides a sqlite-ish execute()/fetchone()/fetchall() surface so existing
call sites keep working. JOINs are resolved in-process (MVP scale).
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Sequence
from urllib.parse import urlparse

from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

_CLIENT: MongoClient | None = None
_LOCK = threading.Lock()
_INITIALIZED = False

TABLES = (
    "users",
    "sessions",
    "consents",
    "profiles",
    "resumes",
    "search_prefs",
    "email_connections",
    "entitlements",
    "payments",
    "companion_tokens",
    "companion_status",
    "jobs",
    "matches",
    "drafts",
    "applications",
    "audit_log",
    "job_queue",
    "qr_payment_submissions",
)

AUTO_ID_TABLES = {"consents", "audit_log", "job_queue"}

# SQLite DEFAULT equivalents applied on insert when callers omit columns.
COLUMN_DEFAULTS: dict[str, dict[str, Any]] = {
    "users": {
        "full_name": "",
        "phone": "",
        "linkedin_url": "",
        "github_url": "",
        "deleted_at": None,
    },
    "profiles": {
        "headline": "",
        "years_experience": 0,
        "skills_json": "[]",
        "summary": "",
    },
    "search_prefs": {
        "roles_json": "[]",
        "locations_json": '["India","Remote"]',
        "work_modes_json": '["remote","hybrid","onsite"]',
        "min_salary_lpa": None,
        "max_years_experience": 3,
        "exclusions_json": "[]",
        "daily_application_limit": 10,
        "preferred_apply_route": "email",
        "auto_send_enabled": 0,
    },
    "entitlements": {
        "plan_id": "free",
        "valid_until": None,
        "matches_used_week": 0,
        "applications_used_month": 0,
        "companion_uploads_used_week": 0,
        "week_key": "",
        "month_key": "",
    },
    "jobs": {
        "apply_email": None,
        "apply_url": None,
        "compensation": None,
        "posted_at": None,
        "compliance_status": "permitted",
        "raw_json": "{}",
    },
    "matches": {
        "missing_requirements": "",
        "status": "new",
    },
    "drafts": {
        "resume_id": None,
        "to_email": None,
        "duplicate_warning": "",
        "sent_at": None,
    },
    "applications": {
        "match_id": None,
        "draft_id": None,
        "job_id": None,
        "stage": "saved",
        "apply_method": "email",
        "notes": "",
        "follow_up_at": None,
    },
    "companion_status": {
        "device_id": "",
        "device_name": "",
        "linkedin_connected": 0,
        "last_sync_at": None,
        "last_sync_count": 0,
        "last_error": "",
    },
    "job_queue": {
        "status": "pending",
        "attempts": 0,
        "completed_at": None,
        "last_error": "",
    },
}


class MongoRow(dict):
    """Dict row that also supports positional index access (e.g. COUNT(*))."""

    def __getitem__(self, key: Any) -> Any:  # type: ignore[override]
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class MongoCursor:
    def __init__(self, rows: list[MongoRow] | None = None, lastrowid: int = 0):
        self._rows = rows or []
        self.lastrowid = lastrowid
        self.rowcount = len(self._rows)

    def fetchone(self) -> MongoRow | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[MongoRow]:
        return list(self._rows)


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip())


def _tls_ca_file() -> str | None:
    try:
        import certifi

        ca = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", ca)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", ca)
        return ca
    except Exception:
        return None


def _client(uri: str) -> MongoClient:
    global _CLIENT
    with _LOCK:
        if _CLIENT is None:
            # Vercel / OpenSSL 3 often fails Atlas OCSP during handshake
            # (TLSV1_ALERT_INTERNAL_ERROR). Disable the extra OCSP HTTP
            # check; certificate verification still uses the CA bundle.
            kwargs: dict[str, Any] = {
                "serverSelectionTimeoutMS": 20000,
                "connectTimeoutMS": 20000,
                "tls": True,
                "tlsDisableOCSPEndpointCheck": True,
            }
            ca = _tls_ca_file()
            if ca:
                kwargs["tlsCAFile"] = ca
            _CLIENT = MongoClient(uri, **kwargs)
        return _CLIENT


def _db_name(uri: str) -> str:
    path = (urlparse(uri).path or "").lstrip("/")
    if path:
        return path.split("?")[0] or "letitapply"
    return "letitapply"


def get_database(uri: str) -> Database:
    return _client(uri)[_db_name(uri)]


def ensure_indexes(uri: str) -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    database = get_database(uri)
    database["users"].create_index("email", unique=True)
    database["users"].create_index("id", unique=True)
    database["sessions"].create_index("token", unique=True)
    database["jobs"].create_index([("source", ASCENDING), ("external_id", ASCENDING)], unique=True)
    database["jobs"].create_index("id", unique=True)
    database["matches"].create_index([("user_id", ASCENDING), ("job_id", ASCENDING)], unique=True)
    database["matches"].create_index("id", unique=True)
    database["drafts"].create_index("id", unique=True)
    database["applications"].create_index("id", unique=True)
    database["companion_tokens"].create_index("token", unique=True)
    database["companion_tokens"].create_index([("user_id", ASCENDING), ("device_id", ASCENDING)])
    database["job_queue"].create_index("idempotency_key", unique=True, sparse=True)
    database["payments"].create_index("id", unique=True)
    database["resumes"].create_index("id", unique=True)
    database["qr_payment_submissions"].create_index("id", unique=True)
    database["qr_payment_submissions"].create_index("transaction_id", unique=True)
    _INITIALIZED = True


def _next_id(database: Database, table: str) -> int:
    doc = database["counters"].find_one_and_update(
        {"_id": table},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


def _doc_to_row(doc: dict[str, Any] | None) -> MongoRow | None:
    if not doc:
        return None
    data = {k: v for k, v in doc.items() if k != "_id"}
    return MongoRow(data)


def _split_csv(text: str) -> list[str]:
    parts: list[str] = []
    buf = ""
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            buf += ch
        elif ch == ")":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _parse_where(where: str, params: list[Any]) -> tuple[dict[str, Any], list[Any]]:
    """Parse a simple AND-only WHERE into a Mongo filter. Consumes params left-to-right."""
    if not where:
        return {}, params
    clauses = re.split(r"\s+AND\s+", where, flags=re.I)
    filt: dict[str, Any] = {}
    remaining = list(params)
    for clause in clauses:
        clause = clause.strip()
        m = re.match(r"(?i)lower\(([a-z0-9_.]+)\)\s*=\s*\?", clause)
        if m:
            field = m.group(1).split(".")[-1]
            val = remaining.pop(0)
            filt[field] = {"$regex": f"^{re.escape(str(val))}$", "$options": "i"}
            continue
        m = re.match(r"(?i)([a-z0-9_.]+)\s+IS\s+NULL", clause)
        if m:
            field = m.group(1).split(".")[-1]
            filt[field] = None
            continue
        m = re.match(r"(?i)([a-z0-9_.]+)\s+IS\s+NOT\s+NULL", clause)
        if m:
            field = m.group(1).split(".")[-1]
            filt[field] = {"$ne": None}
            continue
        m = re.match(r"(?i)([a-z0-9_.]+)\s+IN\s*\((.+)\)", clause)
        if m:
            field = m.group(1).split(".")[-1]
            raw_items = [x.strip().strip("'").strip('"') for x in m.group(2).split(",")]
            filt[field] = {"$in": raw_items}
            continue
        m = re.match(r"(?i)([a-z0-9_.]+)\s*=\s*\?", clause)
        if m:
            field = m.group(1).split(".")[-1]
            filt[field] = remaining.pop(0)
            continue
    return filt, remaining


class MongoConnection:
    def __init__(self, uri: str):
        self.uri = uri
        self.db = get_database(uri)
        self._lastrowid = 0

    def collection(self, name: str) -> Collection:
        if name not in TABLES and name != "counters":
            raise ValueError(f"Unknown table: {name}")
        return self.db[name]

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> MongoCursor:
        params_list = list(params or [])
        sql_n = _normalize_sql(sql)
        upper = sql_n.upper()
        if upper.startswith("PRAGMA") or upper.startswith("ALTER"):
            return MongoCursor([])
        if upper.startswith("SELECT"):
            return self._select(sql_n, params_list)
        if upper.startswith("INSERT"):
            return self._insert(sql_n, params_list)
        if upper.startswith("UPDATE"):
            return self._update(sql_n, params_list)
        if upper.startswith("DELETE"):
            return self._delete(sql_n, params_list)
        raise NotImplementedError(f"Unsupported SQL on Mongo backend: {sql_n[:180]}")

    def _select(self, sql: str, params: list[Any]) -> MongoCursor:
        m = re.match(
            r"(?i)SELECT COUNT\(\*\)(?: AS (\w+))? FROM (\w+)(?: WHERE (.+))?$",
            sql,
        )
        if m:
            alias = m.group(1) or "COUNT(*)"
            table = m.group(2)
            where = m.group(3) or ""
            filt, _ = _parse_where(where, params)
            n = self.collection(table).count_documents(filt)
            return MongoCursor([MongoRow({alias: n, "COUNT(*)": n, "c": n})])

        if re.search(r"(?i)\bJOIN\b", sql):
            return self._select_join(sql, params)

        m = re.match(
            r"(?i)SELECT (.+?) FROM (\w+)(?: WHERE (.+?))?( ORDER BY .+| LIMIT .+)?$",
            sql,
        )
        if not m:
            raise NotImplementedError(f"Unsupported SELECT: {sql[:180]}")
        cols = m.group(1).strip()
        table = m.group(2)
        where = m.group(3) or ""
        tail = m.group(4) or ""

        limit = None
        where_params = params
        if re.search(r"(?i)LIMIT\s+\?", sql):
            limit = int(params[-1])
            where_params = params[:-1]
        else:
            lm = re.search(r"(?i)LIMIT\s+(\d+)", sql)
            if lm:
                limit = int(lm.group(1))

        filt, _ = _parse_where(where, where_params)
        cursor = self.collection(table).find(filt)

        order_m = re.search(r"(?i)ORDER BY (.+?)(?: LIMIT |$)", sql)
        if order_m:
            sort_spec = []
            for part in order_m.group(1).split(","):
                bits = part.strip().split()
                field = bits[0].split(".")[-1]
                direction = DESCENDING if len(bits) > 1 and bits[1].upper().startswith("DESC") else ASCENDING
                sort_spec.append((field, direction))
            if sort_spec:
                cursor = cursor.sort(sort_spec)
        if isinstance(limit, int):
            cursor = cursor.limit(limit)

        rows: list[MongoRow] = []
        for doc in cursor:
            row = _doc_to_row(doc)
            if not row:
                continue
            if cols != "*":
                wanted = [c.strip().split(".")[-1] for c in _split_csv(cols)]
                projected = MongoRow()
                for k in wanted:
                    projected[k] = row.get(k)
                row = projected
            rows.append(row)
        return MongoCursor(rows)

    def _select_join(self, sql: str, params: list[Any]) -> MongoCursor:
        m = re.match(r"(?i)SELECT (.+?) FROM (\w+)(?:\s+(\w+))?\s+(.*)$", sql)
        if not m:
            raise NotImplementedError(f"Unsupported JOIN SELECT: {sql[:180]}")
        base_table = m.group(2)
        base_alias = m.group(3) or base_table
        rest = m.group(4)

        where_m = re.search(r"(?i)\bWHERE\b (.+?)(?= ORDER BY | LIMIT |$)", rest)
        where_sql = where_m.group(1).strip() if where_m else ""
        order_m = re.search(r"(?i)ORDER BY (.+?)(?= LIMIT |$)", rest)
        order_sql = order_m.group(1).strip() if order_m else ""

        if re.search(r"(?i)LIMIT\s+\?", sql):
            limit: int | None = int(params[-1])
            where_params = params[:-1]
        elif re.search(r"(?i)LIMIT\s+(\d+)", sql):
            limit = int(re.search(r"(?i)LIMIT\s+(\d+)", sql).group(1))  # type: ignore[union-attr]
            where_params = params
        else:
            limit = None
            where_params = params

        joins: list[tuple[str, str, str, str, str, bool]] = []
        for jm in re.finditer(
            r"(?i)(LEFT\s+)?JOIN\s+(\w+)(?:\s+(\w+))?\s+ON\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)",
            rest,
        ):
            left_join = bool(jm.group(1))
            right_table = jm.group(2)
            right_alias = jm.group(3) or right_table
            a1, f1, a2, f2 = jm.group(4), jm.group(5), jm.group(6), jm.group(7)
            if a2 == right_alias or a2 == right_table:
                joins.append((a1, right_table, right_alias, f1, f2, left_join))
            else:
                joins.append((a2, right_table, right_alias, f2, f1, left_join))

        extra_filters: list[tuple[str, str, Any]] = []
        remaining = list(where_params)
        if where_sql:
            for clause in re.split(r"\s+AND\s+", where_sql, flags=re.I):
                clause = clause.strip()
                lm = re.match(r"(?i)lower\((\w+)\.(\w+)\)\s*=\s*\?", clause)
                if lm:
                    extra_filters.append((lm.group(1), lm.group(2), ("lower", remaining.pop(0))))
                    continue
                sm = re.match(r"(?i)(\w+)\.(\w+)\s+IS\s+NULL", clause)
                if sm:
                    extra_filters.append((sm.group(1), sm.group(2), ("isnull", None)))
                    continue
                sm = re.match(r"(?i)(\w+)\.(\w+)\s+IS\s+NOT\s+NULL", clause)
                if sm:
                    extra_filters.append((sm.group(1), sm.group(2), ("notnull", None)))
                    continue
                sm = re.match(r"(?i)(\w+)\.(\w+)\s*=\s*\?", clause)
                if sm:
                    extra_filters.append((sm.group(1), sm.group(2), remaining.pop(0)))
                    continue
                sm = re.match(r"(?i)(\w+)\.(\w+)\s+IN\s*\((.+)\)", clause)
                if sm:
                    items = [x.strip().strip("'").strip('"') for x in sm.group(3).split(",")]
                    extra_filters.append((sm.group(1), sm.group(2), ("in", items)))
                    continue

        base_filt: dict[str, Any] = {}
        for alias, field, val in extra_filters:
            if alias != base_alias:
                continue
            if isinstance(val, tuple) and val[0] == "in":
                base_filt[field] = {"$in": val[1]}
            elif isinstance(val, tuple) and val[0] == "lower":
                base_filt[field] = {"$regex": f"^{re.escape(str(val[1]))}$", "$options": "i"}
            elif isinstance(val, tuple) and val[0] == "isnull":
                base_filt[field] = None
            elif isinstance(val, tuple) and val[0] == "notnull":
                base_filt[field] = {"$ne": None}
            else:
                base_filt[field] = val

        base_docs = list(self.collection(base_table).find(base_filt))
        results: list[dict[str, Any]] = []

        # Detect "alias.col AS name" projections from the SELECT list
        select_list = m.group(1)
        aliases_out: list[tuple[str, str, str]] = []  # alias, field, out_name
        for part in _split_csv(select_list):
            am = re.match(r"(?i)(\w+)\.(\w+)\s+AS\s+(\w+)$", part.strip())
            if am:
                aliases_out.append((am.group(1), am.group(2), am.group(3)))

        for base in base_docs:
            row: dict[str, Any] = {k: v for k, v in base.items() if k != "_id"}
            base_id = row.get("id")
            base_snapshot = dict(row)
            skip = False
            for left_alias, right_table, right_alias, left_field, right_field, left_join in joins:
                # Resolve left value from the correct side
                if left_alias == base_alias:
                    left_val = base_snapshot.get(left_field)
                else:
                    left_val = row.get(left_field)
                matched = None
                if left_val is not None:
                    matched = self.collection(right_table).find_one({right_field: left_val})
                if matched is None:
                    if left_join:
                        continue
                    skip = True
                    break
                if right_table == "jobs":
                    for fld in (
                        "title",
                        "company",
                        "location",
                        "source",
                        "source_url",
                        "apply_email",
                        "apply_url",
                        "compensation",
                        "description",
                    ):
                        if fld in matched:
                            row[fld] = matched[fld]
                elif right_table == "users":
                    for fld in (
                        "email",
                        "full_name",
                        "password_hash",
                        "phone",
                        "linkedin_url",
                        "github_url",
                        "deleted_at",
                        "created_at",
                    ):
                        if fld in matched:
                            row[fld] = matched[fld]
                    row["id"] = matched.get("id", row.get("id"))
                elif right_table == "drafts":
                    for fld in ("to_email", "subject", "body", "status", "duplicate_warning"):
                        if fld in matched:
                            row[fld] = matched[fld]
                    row["draft_id"] = matched.get("id")
                elif right_table == "matches":
                    for k, v in matched.items():
                        if k not in {"_id", "id"}:
                            row[k] = v
                    row["match_id"] = matched.get("id")
                else:
                    for k, v in matched.items():
                        if k not in {"_id", "id"}:
                            row[k] = v
            if skip:
                continue

            # Apply AS projections (e.g. s.expires_at AS session_expires_at)
            for alias, field, out_name in aliases_out:
                if alias == base_alias:
                    row[out_name] = base_snapshot.get(field)
                else:
                    row.setdefault(out_name, row.get(field))

            if base_table == "matches" and base_id:
                row["id"] = base_id
            if base_table == "drafts" and base_id:
                row["id"] = base_id
            if base_table == "applications" and base_id:
                row["id"] = base_id

            ok = True
            for alias, field, val in extra_filters:
                if alias == base_alias:
                    continue
                cur = row.get(field)
                if isinstance(val, tuple) and val[0] == "lower":
                    if (cur or "").lower() != str(val[1]).lower():
                        ok = False
                        break
                elif isinstance(val, tuple) and val[0] == "in":
                    if cur not in val[1]:
                        ok = False
                        break
                elif isinstance(val, tuple) and val[0] == "isnull":
                    if cur is not None:
                        ok = False
                        break
                elif isinstance(val, tuple) and val[0] == "notnull":
                    if cur is None:
                        ok = False
                        break
                elif cur != val:
                    ok = False
                    break
            if not ok:
                continue
            results.append(row)

        if order_sql:
            keys: list[tuple[str, bool]] = []
            for part in order_sql.split(","):
                bits = part.strip().split()
                field = bits[0].split(".")[-1]
                reverse = len(bits) > 1 and bits[1].upper().startswith("DESC")
                keys.append((field, reverse))
            for field, reverse in reversed(keys):
                results.sort(key=lambda r, f=field: (r.get(f) is None, r.get(f)), reverse=reverse)

        if limit is not None:
            results = results[:limit]
        return MongoCursor([MongoRow(r) for r in results])

    def _insert(self, sql: str, params: list[Any]) -> MongoCursor:
        ignore = bool(re.match(r"(?i)INSERT OR IGNORE", sql))
        m = re.match(
            r"(?i)INSERT(?: OR IGNORE)? INTO (\w+)\s*\((.+?)\)\s*VALUES\s*\((.+?)\)(?:\s+ON CONFLICT\((.+?)\)\s+DO UPDATE SET\s+(.+))?$",
            sql,
        )
        if not m:
            raise NotImplementedError(f"Unsupported INSERT: {sql[:180]}")
        table = m.group(1)
        cols = [c.strip() for c in m.group(2).split(",")]
        conflict_key = m.group(4).strip() if m.group(4) else None
        update_set = m.group(5).strip() if m.group(5) else None

        doc = {col: params[i] if i < len(params) else None for i, col in enumerate(cols)}
        for key, default in COLUMN_DEFAULTS.get(table, {}).items():
            doc.setdefault(key, default)
        lastrowid = 0
        if table in AUTO_ID_TABLES and "id" not in doc:
            lastrowid = _next_id(self.db, table)
            doc["id"] = lastrowid
        self._lastrowid = lastrowid

        coll = self.collection(table)
        if conflict_key and update_set:
            key_val = doc[conflict_key]
            set_doc: dict[str, Any] = {}
            for part in _split_csv(update_set):
                if "=" not in part:
                    continue
                left, right = [x.strip() for x in part.split("=", 1)]
                cm = re.match(
                    r"(?i)COALESCE\(NULLIF\(excluded\.(\w+),''\),\s*\w+\.(\w+)\)",
                    right,
                )
                if cm:
                    new_v = doc.get(cm.group(1))
                    if new_v not in (None, ""):
                        set_doc[left] = new_v
                    continue
                cm = re.match(r"(?i)COALESCE\(excluded\.(\w+),\s*\w+\.(\w+)\)", right)
                if cm:
                    new_v = doc.get(cm.group(1))
                    if new_v is not None:
                        set_doc[left] = new_v
                    continue
                cm = re.match(r"(?i)excluded\.(\w+)$", right)
                if cm:
                    set_doc[left] = doc.get(cm.group(1))
                    continue
                set_doc[left] = doc.get(left)
            merged = {**doc, **set_doc}
            coll.update_one({conflict_key: key_val}, {"$set": merged}, upsert=True)
            return MongoCursor([], lastrowid=lastrowid)

        try:
            coll.insert_one(doc)
        except DuplicateKeyError:
            if ignore:
                return MongoCursor([], lastrowid=0)
            raise
        rid = lastrowid
        if not rid and isinstance(doc.get("id"), int):
            rid = int(doc["id"])
        return MongoCursor([], lastrowid=rid)

    def _update(self, sql: str, params: list[Any]) -> MongoCursor:
        m = re.match(r"(?i)UPDATE (\w+) SET (.+?) WHERE (.+)$", sql)
        if not m:
            raise NotImplementedError(f"Unsupported UPDATE: {sql[:180]}")
        table = m.group(1)
        set_sql = m.group(2)
        where_sql = m.group(3)
        set_parts = _split_csv(set_sql)
        set_param_count = sum(p.count("?") for p in set_parts)
        set_params = params[:set_param_count]
        where_params = params[set_param_count:]
        filt, _ = _parse_where(where_sql, where_params)

        sets: dict[str, Any] = {}
        incs: dict[str, Any] = {}
        pi = 0
        for part in set_parts:
            left, right = [x.strip() for x in part.split("=", 1)]
            if re.search(rf"(?i)^{re.escape(left)}\s*\+\s*1$", right):
                incs[left] = 1
                continue
            if re.match(r"(?i)COALESCE\(\?,\s*" + re.escape(left) + r"\)$", right):
                val = set_params[pi]
                pi += 1
                if val is not None:
                    sets[left] = val
                continue
            if right == "?":
                sets[left] = set_params[pi]
                pi += 1
                continue
            if right.upper() == "NULL":
                sets[left] = None
            elif right.isdigit():
                sets[left] = int(right)
            else:
                sets[left] = right.strip("'").strip('"')

        update_doc: dict[str, Any] = {}
        if sets:
            update_doc["$set"] = sets
        if incs:
            update_doc["$inc"] = incs
        if update_doc:
            self.collection(table).update_many(filt, update_doc)
        return MongoCursor([])

    def _delete(self, sql: str, params: list[Any]) -> MongoCursor:
        m = re.match(r"(?i)DELETE FROM (\w+)(?: WHERE (.+))?$", sql)
        if not m:
            raise NotImplementedError(f"Unsupported DELETE: {sql[:180]}")
        table = m.group(1)
        where = m.group(2) or ""
        if not where:
            raise RuntimeError("Refusing DELETE without WHERE on Mongo backend")
        filt, _ = _parse_where(where, params)
        self.collection(table).delete_many(filt)
        return MongoCursor([])

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


@contextmanager
def connect_mongo(uri: str) -> Iterator[MongoConnection]:
    ensure_indexes(uri)
    conn = MongoConnection(uri)
    try:
        yield conn
    except Exception:
        raise

"""Odoo XML-RPC client helper — Python stdlib only.

Used by US-004 ~ US-011 scripts in the greenpr demo-full-flow PRD.

Connection parameters resolve in this order (first non-empty wins):
    1) Explicit constructor args
    2) Environment variables: ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_PASSWORD
    3) Defaults geared for in-container execution on the greenpr tenant
       (http://localhost:8069, db=odoo, login=admin, password=admin)

Typical use (inside `docker exec ycerp-web-greenpr python3 ...`):

    from odoo_client import OdooClient
    cli = OdooClient()
    uid = cli.authenticate()
    partners = cli.search_read("res.partner", [("customer_rank", ">", 0)],
                                ["id", "name"], limit=5)

Execution from the host is also supported by passing the gateway URL:

    OdooClient(url="http://localhost:30033")
"""

from __future__ import annotations

import os
import xmlrpc.client
from typing import Any, Iterable, Sequence


DEFAULT_URL = "http://localhost:8069"
DEFAULT_DB = "odoo"
DEFAULT_LOGIN = "admin"
DEFAULT_PASSWORD = "admin"


class OdooAuthError(RuntimeError):
    pass


class OdooClient:
    def __init__(
        self,
        url: str | None = None,
        db: str | None = None,
        login: str | None = None,
        password: str | None = None,
    ) -> None:
        self.url = url or os.environ.get("ODOO_URL") or DEFAULT_URL
        self.db = db or os.environ.get("ODOO_DB") or DEFAULT_DB
        self.login = login or os.environ.get("ODOO_LOGIN") or DEFAULT_LOGIN
        self.password = (
            password or os.environ.get("ODOO_PASSWORD") or DEFAULT_PASSWORD
        )
        self._common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common", allow_none=True
        )
        self._object = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", allow_none=True
        )
        self._uid: int | None = None

    def version(self) -> dict[str, Any]:
        return self._common.version()

    def authenticate(self) -> int:
        uid = self._common.authenticate(self.db, self.login, self.password, {})
        if not uid:
            raise OdooAuthError(
                f"authenticate failed for db={self.db!r} login={self.login!r} "
                f"at {self.url}"
            )
        self._uid = int(uid)
        return self._uid

    @property
    def uid(self) -> int:
        if self._uid is None:
            self.authenticate()
        assert self._uid is not None
        return self._uid

    def execute_kw(
        self,
        model: str,
        method: str,
        args: Sequence[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        return self._object.execute_kw(
            self.db,
            self.uid,
            self.password,
            model,
            method,
            list(args or []),
            dict(kwargs or {}),
        )

    def search(
        self,
        model: str,
        domain: Iterable[Any] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[int]:
        kw: dict[str, Any] = {"offset": offset}
        if limit is not None:
            kw["limit"] = limit
        if order is not None:
            kw["order"] = order
        return self.execute_kw(model, "search", [list(domain or [])], kw)

    def search_read(
        self,
        model: str,
        domain: Iterable[Any] | None = None,
        fields: Sequence[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kw: dict[str, Any] = {"offset": offset}
        if fields:
            kw["fields"] = list(fields)
        if limit is not None:
            kw["limit"] = limit
        if order is not None:
            kw["order"] = order
        return self.execute_kw(model, "search_read", [list(domain or [])], kw)

    def read(
        self,
        model: str,
        ids: Sequence[int],
        fields: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        kw: dict[str, Any] = {}
        if fields:
            kw["fields"] = list(fields)
        return self.execute_kw(model, "read", [list(ids)], kw)

    def create(self, model: str, values: dict[str, Any] | list[dict[str, Any]]) -> Any:
        payload = values if isinstance(values, list) else [values]
        return self.execute_kw(model, "create", [payload])

    def write(
        self,
        model: str,
        ids: Sequence[int],
        values: dict[str, Any],
    ) -> bool:
        return self.execute_kw(model, "write", [list(ids), values])

    def unlink(self, model: str, ids: Sequence[int]) -> bool:
        return self.execute_kw(model, "unlink", [list(ids)])

    def call_method(
        self,
        model: str,
        method: str,
        ids: Sequence[int] | None = None,
        *extra_args: Any,
        **kwargs: Any,
    ) -> Any:
        """Invoke a model method.

        For recordset-bound methods, pass the record ids (first positional arg
        becomes the ids list, matching Odoo's execute_kw convention).
        For classmethod/free calls, leave `ids` as None.
        """
        args: list[Any] = []
        if ids is not None:
            args.append(list(ids))
        args.extend(extra_args)
        return self.execute_kw(model, method, args, kwargs)

    def fields_get(
        self,
        model: str,
        attributes: Sequence[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        kw: dict[str, Any] = {}
        if attributes:
            kw["attributes"] = list(attributes)
        return self.execute_kw(model, "fields_get", [], kw)

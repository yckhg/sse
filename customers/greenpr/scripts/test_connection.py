"""Sanity test for odoo_client.OdooClient against the greenpr tenant.

Run from inside the web container to keep things self-contained:

    docker cp customers/greenpr/scripts ycerp-web-greenpr:/tmp/
    docker exec ycerp-web-greenpr python3 /tmp/scripts/test_connection.py

Or from the host against the gateway port:

    ODOO_URL=http://localhost:30033 python3 \\
        customers/greenpr/scripts/test_connection.py

Exit code 0 on success, non-zero on any failed check.
"""

from __future__ import annotations

import sys

from odoo_client import OdooClient


def main() -> int:
    cli = OdooClient()
    print(f"target: url={cli.url} db={cli.db} login={cli.login}")

    version = cli.version()
    server_version = version.get("server_version", "?")
    print(f"  version.server_version = {server_version}")
    if not str(server_version).startswith("19.0"):
        print("  FAIL: expected Odoo 19.0 series")
        return 2

    uid = cli.authenticate()
    print(f"  authenticate.uid = {uid}")
    if uid != 2:
        print("  FAIL: expected admin uid=2 on greenpr")
        return 3

    partners = cli.search_read(
        "res.partner", [("active", "=", True)], ["id", "name"], limit=3, order="id asc"
    )
    print(f"  search_read(res.partner) -> {len(partners)} rows")
    if not partners:
        print("  FAIL: search_read returned no partners")
        return 4
    for p in partners:
        print(f"    - id={p['id']} name={p['name']!r}")

    so_count = cli.execute_kw(
        "sale.order",
        "search_count",
        [[("date_order", ">=", "2026-03-17")]],
    )
    print(f"  sale.order (date_order>=2026-03-17) search_count = {so_count}")
    if so_count <= 0:
        print("  FAIL: expected recent sale.order rows (US-002 baseline)")
        return 5

    partner_fields = cli.fields_get("res.partner", attributes=["type", "string"])
    must_have = {"name", "email", "customer_rank"}
    missing = must_have - set(partner_fields)
    if missing:
        print(f"  FAIL: res.partner fields missing: {missing}")
        return 6
    print(f"  fields_get(res.partner) has {len(partner_fields)} fields")

    print("OK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

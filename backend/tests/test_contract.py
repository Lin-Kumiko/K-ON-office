"""API contract: OpenAPI vs. real routes, response schemas, pagination and error structure."""
import re

import pytest
from pydantic import TypeAdapter

from tests.conftest import ok


def test_openapi_covers_every_route(app, client):
    spec = client.get("/openapi.json").json()
    documented = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    actual = set()
    for r in app.routes:
        if getattr(r, "include_in_schema", True) and hasattr(r, "methods") and r.path.startswith("/api"):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                actual.add((m, r.path))
    assert actual == documented
    assert len(documented) > 200
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert op.get("summary"), f"{method} {path} lacks summary"
            if path not in ("/api/health", "/api/auth/login"):
                assert "401" in op["responses"] or "403" in op["responses"], f"{method} {path} lacks error docs"


def _response_model(app, path, method):
    for r in app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return getattr(r, "response_model", None)
    return None


GETS = [
    "/api/auth/me", "/api/auth/sessions", "/api/users", "/api/roles", "/api/permissions", "/api/audit-logs",
    "/api/login-logs", "/api/settings", "/api/holidays?year=2026", "/api/departments", "/api/departments/tree",
    "/api/positions", "/api/employees", "/api/employees/options", "/api/leave/types", "/api/leave/balances",
    "/api/leave/ledger", "/api/leave/requests", "/api/attendance/rules", "/api/attendance/monthly?month=2026-10",
    "/api/attendance/records?start=2026-10-01&end=2026-10-19", "/api/attendance/corrections",
    "/api/attendance/overtime", "/api/travel", "/api/expense/categories", "/api/expense/claims",
    "/api/meeting/rooms", "/api/meeting/bookings", "/api/meeting/calendar?start=2026-10-01&end=2026-10-31",
    "/api/announcements", "/api/announcements/categories", "/api/notifications", "/api/schedules?start=2026-10-01&end=2026-10-31",
    "/api/documents", "/api/documents/categories", "/api/recruitment/requisitions", "/api/recruitment/candidates",
    "/api/recruitment/offers", "/api/recruitment/interviews", "/api/onboarding", "/api/onboarding-tasks",
    "/api/regularization", "/api/regularization/probation-employees", "/api/transfers", "/api/performance/cycles",
    "/api/performance/reviews", "/api/payroll/structures", "/api/payroll/runs", "/api/payroll/my-payslips",
    "/api/workflow/definitions", "/api/workflow/business-types", "/api/workflow/instances", "/api/workflow/tasks",
    "/api/workflow/cc", "/api/dashboard/summary", "/api/reports/overview",
]


@pytest.mark.parametrize("url", GETS)
def test_get_endpoints_match_declared_schema(app, as_user, url):
    body = ok(as_user("ui").get(url))
    path = url.split("?")[0]
    model = _response_model(app, path, "GET")
    if model is not None:
        TypeAdapter(model).validate_python(body)  # raises if implementation drifts from the contract
    if isinstance(body, dict) and "items" in body:
        assert set(body) == {"items", "total", "page", "page_size"}


def test_pagination_contract(as_user):
    admin = as_user("ui")
    p1 = ok(admin.get("/api/employees?page=1&page_size=5&sort=employee_no"))
    p3 = ok(admin.get("/api/employees?page=3&page_size=5&sort=employee_no"))
    assert p1["total"] == 13 and len(p1["items"]) == 5 and len(p3["items"]) == 3
    assert p1["items"][0]["employee_no"] == "HTT0001"
    desc = ok(admin.get("/api/employees?page_size=1&sort=-employee_no"))
    assert desc["items"][0]["employee_no"] == "HTT0013"
    assert ok(admin.get("/api/employees?page=99"))["items"] == []


@pytest.mark.parametrize("method,url", [("get", "/api/employees/999999"), ("post", "/api/workflow/tasks/999999/approve"),
                                        ("get", "/api/workflow/instances/999999"), ("get", "/api/travel/999999")])
def test_not_found_error_shape(as_user, method, url):
    r = getattr(as_user("ui"), method)(url, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}


PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register", "/api/public/overview",
                "/api/departments", "/api/departments/tree", "/api/positions", "/api/announcements",
                "/api/announcements/categories", "/api/announcements/{aid}", "/api/documents",
                "/api/documents/categories", "/api/documents/{doc_id}", "/api/meeting/rooms",
                "/api/meeting/calendar", "/api/meeting/rooms/{room_id}/availability"}


def test_unauthenticated_error_shape_everywhere(client):
    """Every operation except the documented public read endpoints asks an anonymous caller to log in."""
    spec = client.get("/openapi.json").json()
    checked = 0
    for path, ops in spec["paths"].items():
        for method in ops:
            if path in PUBLIC_PATHS and method == "get":
                continue
            if path in ("/api/auth/login", "/api/auth/register"):
                continue
            url = re.sub(r"\{[^}]+\}", "1", path)
            r = client.request(method.upper(), url)
            assert r.status_code in (401, 422), f"{method} {path} -> {r.status_code}"
            if r.status_code == 401:
                assert r.json()["error"]["code"] == "LOGIN_REQUIRED", f"{method} {path}"
            checked += 1
    assert checked > 200
    public_gets = {p for p, ops in spec["paths"].items() if "get" in ops and p in PUBLIC_PATHS}
    assert public_gets == PUBLIC_PATHS - {"/api/auth/login", "/api/auth/register"}

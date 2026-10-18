from tests.conftest import err, ok


def test_health_and_login(client, as_user):
    assert ok(client.get("/api/health"))["status"] == "ok"
    me = ok(as_user("yui").get("/api/auth/me"))
    assert me["employee"]["name"] == "平泽唯"
    assert "leave:apply" in me["permissions"]
    err(client.get("/api/auth/me"), 401, "LOGIN_REQUIRED")


def test_seed_workflows_are_valid(as_user):
    defs = ok(as_user("ui").get("/api/workflow/definitions"))
    assert len(defs) == 10
    for d in defs:
        res = ok(as_user("ui").post(f"/api/workflow/definitions/{d['id']}/validate",
                                       json={"graph": ok(as_user("ui").get(f"/api/workflow/definitions/{d['id']}"))["versions"][0]["graph"]}))
        assert res["valid"], (d["key"], res["errors"])

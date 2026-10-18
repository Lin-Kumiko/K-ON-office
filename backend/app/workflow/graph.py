"""Workflow graph model, static validation and the restricted condition language.

Conditions are plain JSON, never code:
    {"all": [ {"field": "amount", "op": ">", "value": 5000}, {"any": [...]} ]}
Allowed ops: == != > >= < <= in not_in. Fields must be declared variables of the
business type; values are type-checked at publish time.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from typing import Any

NODE_TYPES = {"start", "end", "approval", "condition", "parallel", "join", "cc"}
APPROVER_TYPES = {"user", "role", "direct_manager", "department_manager", "hr_admin", "amount_based"}
OPS = {"==", "!=", ">", ">=", "<", "<=", "in", "not_in"}
NUMERIC_OPS = {">", ">=", "<", "<="}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_CONDITION_DEPTH = 4


class Graph:
    def __init__(self, data: dict):
        self.data = data
        self.nodes: dict[str, dict] = {n["id"]: n for n in data.get("nodes", []) if isinstance(n, dict) and "id" in n}
        self.edges: list[dict] = [e for e in data.get("edges", []) if isinstance(e, dict)]
        self.out: dict[str, list[dict]] = defaultdict(list)
        self.inc: dict[str, list[dict]] = defaultdict(list)
        for e in self.edges:
            self.out[e.get("source")].append(e)
            self.inc[e.get("target")].append(e)
        for lst in self.out.values():
            lst.sort(key=lambda e: (bool(e.get("default")), e.get("priority", 100)))

    def node(self, node_id: str) -> dict:
        return self.nodes[node_id]

    def start_id(self) -> str:
        return next(nid for nid, n in self.nodes.items() if n.get("type") == "start")


# ------------------------------------------------------------------ conditions
def _num(v: Any) -> Decimal:
    if isinstance(v, bool):
        raise TypeError("bool is not numeric")
    return Decimal(str(v))


def evaluate(cond: dict | None, variables: dict, depth: int = 0) -> bool:
    if cond is None:
        return True
    if depth > MAX_CONDITION_DEPTH:
        raise ValueError("condition too deep")
    if "all" in cond:
        return all(evaluate(c, variables, depth + 1) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, variables, depth + 1) for c in cond["any"])
    field, op, value = cond["field"], cond["op"], cond.get("value")
    actual = variables.get(field)
    if actual is None:
        return False
    try:
        if op in NUMERIC_OPS:
            a, b = _num(actual), _num(value)
            return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]
        if op in ("==", "!="):
            if isinstance(actual, (int, float, Decimal)) and not isinstance(actual, bool):
                eq = _num(actual) == _num(value)
            else:
                eq = str(actual) == str(value)
            return eq if op == "==" else not eq
        if op in ("in", "not_in"):
            members = {str(x) for x in (value or [])}
            hit = str(actual) in members
            return hit if op == "in" else not hit
    except (InvalidOperation, TypeError, ValueError):
        return False
    return False


def validate_condition(cond: Any, variables: dict[str, str], path: str, errors: list[str], depth: int = 0) -> None:
    if depth > MAX_CONDITION_DEPTH:
        errors.append(f"{path}: 条件嵌套过深（最多 {MAX_CONDITION_DEPTH} 层）")
        return
    if not isinstance(cond, dict):
        errors.append(f"{path}: 条件必须是对象")
        return
    for key in ("all", "any"):
        if key in cond:
            items = cond[key]
            if not isinstance(items, list) or not items:
                errors.append(f"{path}: {key} 必须是非空数组")
                return
            for i, c in enumerate(items):
                validate_condition(c, variables, f"{path}.{key}[{i}]", errors, depth + 1)
            return
    field, op = cond.get("field"), cond.get("op")
    if field not in variables:
        errors.append(f"{path}: 字段 {field!r} 不是该业务类型可用变量（可用：{', '.join(sorted(variables))}）")
        return
    if op not in OPS:
        errors.append(f"{path}: 不支持的运算符 {op!r}")
        return
    value = cond.get("value")
    vtype = variables[field]
    if op in ("in", "not_in"):
        if not isinstance(value, list) or not value:
            errors.append(f"{path}: {op} 需要非空数组")
        return
    if op in NUMERIC_OPS and vtype != "number":
        errors.append(f"{path}: 字段 {field} 不是数值，不能使用 {op}")
        return
    if vtype == "number":
        try:
            _num(value)
        except (InvalidOperation, TypeError, ValueError):
            errors.append(f"{path}: 值 {value!r} 不是有效数字")


# ------------------------------------------------------------------ approver config
def validate_approver(cfg: Any, path: str, errors: list[str], roles: set[str], users: set[int],
                      variables: dict[str, str], depth: int = 0) -> None:
    if not isinstance(cfg, dict) or cfg.get("type") not in APPROVER_TYPES:
        errors.append(f"{path}: 审批人策略必须是 {sorted(APPROVER_TYPES)} 之一")
        return
    t = cfg["type"]
    if t == "user":
        ids = cfg.get("user_ids")
        if not isinstance(ids, list) or not ids:
            errors.append(f"{path}: 指定用户策略需要 user_ids")
        elif any(i not in users for i in ids):
            errors.append(f"{path}: user_ids 包含不存在或已停用的用户")
    elif t == "role":
        if cfg.get("role_code") not in roles:
            errors.append(f"{path}: 角色 {cfg.get('role_code')!r} 不存在")
    elif t == "department_manager":
        var = cfg.get("department_var")
        if var is not None and var not in variables:
            errors.append(f"{path}: department_var {var!r} 不是可用变量")
        level = cfg.get("level", 1)
        if not isinstance(level, int) or not 1 <= level <= 5:
            errors.append(f"{path}: level 需为 1-5")
    elif t == "amount_based":
        if depth > 0:
            errors.append(f"{path}: amount_based 不能嵌套")
            return
        field = cfg.get("field", "amount")
        if variables.get(field) != "number":
            errors.append(f"{path}: 金额字段 {field!r} 不是数值变量")
        rules = cfg.get("rules")
        if not isinstance(rules, list) or not rules:
            errors.append(f"{path}: amount_based 需要 rules")
            return
        if rules[-1].get("max") is not None:
            errors.append(f"{path}: 最后一条规则的 max 必须为空（兜底）")
        prev = None
        for i, r in enumerate(rules):
            mx = r.get("max")
            if mx is not None:
                try:
                    mxd = _num(mx)
                except (InvalidOperation, TypeError, ValueError):
                    errors.append(f"{path}.rules[{i}]: max 不是数字")
                    continue
                if prev is not None and mxd <= prev:
                    errors.append(f"{path}.rules[{i}]: max 需递增")
                prev = mxd
            validate_approver(r.get("approver"), f"{path}.rules[{i}].approver", errors, roles, users, variables,
                              depth + 1)


# ------------------------------------------------------------------ graph validation
def validate_graph(data: Any, variables: dict[str, str], roles: set[str], users: set[int]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list) or not isinstance(data.get("edges"), list):
        return ["流程图必须包含 nodes 与 edges 数组"]
    if len(data["nodes"]) > 200 or len(data["edges"]) > 400:
        return ["流程节点或连线数量过多"]
    seen: set[str] = set()
    for i, n in enumerate(data["nodes"]):
        if not isinstance(n, dict):
            errors.append(f"nodes[{i}]: 节点必须是对象")
            continue
        nid = n.get("id")
        if not isinstance(nid, str) or not _ID_RE.match(nid):
            errors.append(f"nodes[{i}]: 节点 id 非法")
            continue
        if nid in seen:
            errors.append(f"节点 id 重复：{nid}")
        seen.add(nid)
        if n.get("type") not in NODE_TYPES:
            errors.append(f"节点 {nid}: 类型 {n.get('type')!r} 不支持")
        name = n.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            errors.append(f"节点 {nid}: 名称必填且不超过 128 字")
    if errors:
        return errors
    g = Graph(data)
    edge_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for i, e in enumerate(g.edges):
        eid = e.get("id")
        if not isinstance(eid, str) or not _ID_RE.match(eid):
            errors.append(f"edges[{i}]: 连线 id 非法")
            continue
        if eid in edge_ids:
            errors.append(f"连线 id 重复：{eid}")
        edge_ids.add(eid)
        s, t = e.get("source"), e.get("target")
        if s not in g.nodes or t not in g.nodes:
            errors.append(f"连线 {eid}: 起点或终点不存在")
            continue
        if s == t:
            errors.append(f"连线 {eid}: 不能连接自身")
        if (s, t) in pairs:
            errors.append(f"连线 {eid}: 重复连线 {s}→{t}")
        pairs.add((s, t))
    if errors:
        return errors

    starts = [nid for nid, n in g.nodes.items() if n["type"] == "start"]
    ends = [nid for nid, n in g.nodes.items() if n["type"] == "end"]
    if len(starts) != 1:
        errors.append("必须且只能有一个开始节点")
    if not ends:
        errors.append("至少需要一个结束节点")
    for nid, n in g.nodes.items():
        t = n["type"]
        outs, ins = g.out.get(nid, []), g.inc.get(nid, [])
        label = f"节点 {n.get('name')}({nid})"
        if t == "start":
            if ins:
                errors.append(f"{label}: 开始节点不能有入线")
            if len(outs) != 1:
                errors.append(f"{label}: 开始节点必须有且只有一条出线")
        elif t == "end":
            if outs:
                errors.append(f"{label}: 结束节点不能有出线")
            if not ins:
                errors.append(f"{label}: 结束节点没有入线")
        else:
            if not ins:
                errors.append(f"{label}: 没有入线（不可达）")
            if t in ("approval", "cc", "join") and len(outs) != 1:
                errors.append(f"{label}: 必须有且只有一条出线")
            if t == "condition":
                if len(outs) < 2:
                    errors.append(f"{label}: 条件分支至少需要两条出线")
                defaults = [e for e in outs if e.get("default")]
                if len(defaults) != 1:
                    errors.append(f"{label}: 条件分支必须有且只有一条默认出线")
                for e in outs:
                    if not e.get("default"):
                        if "condition" not in e:
                            errors.append(f"{label}: 连线 {e['id']} 缺少条件")
                        else:
                            validate_condition(e["condition"], variables, f"连线 {e['id']}", errors)
            if t == "parallel" and len(outs) < 2:
                errors.append(f"{label}: 并行分支至少需要两条出线")
            if t == "join" and len(ins) < 2:
                errors.append(f"{label}: 汇聚节点至少需要两条入线")
            if t == "approval":
                cfg = n.get("config") or {}
                validate_approver(cfg.get("approver"), f"{label}.approver", errors, roles, users, variables)
                if cfg.get("mode", "or") not in ("or", "and"):
                    errors.append(f"{label}: mode 只能是 or（或签）/ and（会签）")
                if cfg.get("on_empty", "fallback") not in ("fallback", "auto_pass", "error"):
                    errors.append(f"{label}: on_empty 只能是 fallback / auto_pass / error")
            if t == "cc":
                cfg = n.get("config") or {}
                validate_approver(cfg.get("targets"), f"{label}.targets", errors, roles, users, variables)
        if t != "condition":
            for e in outs:
                if "condition" in e and e["condition"] is not None:
                    errors.append(f"{label}: 只有条件节点的出线可以设置条件")
    if errors:
        return errors

    # acyclic
    indeg = {nid: len(g.inc.get(nid, [])) for nid in g.nodes}
    q = deque(nid for nid, d in indeg.items() if d == 0)
    visited = 0
    while q:
        cur = q.popleft()
        visited += 1
        for e in g.out.get(cur, []):
            indeg[e["target"]] -= 1
            if indeg[e["target"]] == 0:
                q.append(e["target"])
    if visited != len(g.nodes):
        return ["流程图存在环路，审批流程必须是有向无环图"]

    # reachability both ways
    start = starts[0]
    fwd = _reach(start, lambda x: [e["target"] for e in g.out.get(x, [])])
    for nid in g.nodes:
        if nid not in fwd:
            errors.append(f"节点 {g.nodes[nid]['name']}({nid}) 从开始节点不可达")
    bwd: set[str] = set()
    for end in ends:
        bwd |= _reach(end, lambda x: [e["source"] for e in g.inc.get(x, [])])
    for nid in g.nodes:
        if nid not in bwd:
            errors.append(f"节点 {g.nodes[nid]['name']}({nid}) 无法到达结束节点")
    if errors:
        return errors

    # parallel regions must converge in a single join
    memo: dict[str, str | None] = {}
    for nid, n in g.nodes.items():
        if n["type"] == "parallel":
            _matching_join(g, nid, memo, errors)
    for nid, n in g.nodes.items():
        if n["type"] == "join" and nid not in memo.values():
            errors.append(f"汇聚节点 {n['name']}({nid}) 没有对应的并行分支")
    return list(dict.fromkeys(errors))


def _reach(start: str, nxt) -> set[str]:
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(nxt(cur))
    return seen


def _matching_join(g: Graph, pid: str, memo: dict, errors: list[str]) -> str | None:
    if pid in memo:
        return memo[pid]
    memo[pid] = None
    branch_nodes: list[set[str]] = []
    joins: set[str] = set()
    ok = True
    for e in g.out.get(pid, []):
        nodes, reached, hit_end = _walk_branch(g, e["target"], memo, errors)
        if hit_end:
            errors.append(f"并行节点 {g.nodes[pid]['name']}({pid}) 的分支未经汇聚直接结束")
            ok = False
        branch_nodes.append(nodes)
        joins |= reached
    if len(joins) != 1:
        if ok:
            errors.append(f"并行节点 {g.nodes[pid]['name']}({pid}) 的分支必须汇聚到同一个汇聚节点")
        return None
    for i in range(len(branch_nodes)):
        for j in range(i + 1, len(branch_nodes)):
            if branch_nodes[i] & branch_nodes[j]:
                errors.append(f"并行节点 {g.nodes[pid]['name']}({pid}) 的分支在汇聚前共享节点")
                return None
    join = joins.pop()
    if len(g.inc.get(join, [])) != len(g.out.get(pid, [])):
        errors.append(f"汇聚节点 {g.nodes[join]['name']}({join}) 的入线数需与并行分支数一致")
    memo[pid] = join
    return join


def _walk_branch(g: Graph, start: str, memo: dict, errors: list[str]) -> tuple[set[str], set[str], bool]:
    nodes: set[str] = set()
    joins: set[str] = set()
    hit_end = False
    stack = [start]
    while stack:
        cur = stack.pop()
        if cur in nodes:
            continue
        t = g.nodes[cur]["type"]
        if t == "join":
            joins.add(cur)
            continue
        nodes.add(cur)
        if t == "end":
            hit_end = True
            continue
        if t == "parallel":
            inner = _matching_join(g, cur, memo, errors)
            if inner is None:
                continue
            nodes.add(inner)
            stack.extend(e["target"] for e in g.out.get(inner, []))
            continue
        stack.extend(e["target"] for e in g.out.get(cur, []))
    return nodes, joins, hit_end

"""通过真实 HTTP 接口复现“复核员一次提交 G1/G2、G1 被并发驳回”的验收场景。

用法：
    python3 scripts/verify_http.py
前置：后端已在 http://127.0.0.1:8021 运行（./run.sh）。

断言覆盖：
- 多选提交只处理显式勾选的 id/候选组；
- G1 受理前已被其他复核员驳回 -> 逐条回执为处置冲突，驳回结论保留；
- G2 部分成功 -> 复核通过与金记录合并确认成对，具备发布领用资格；
- 整组回执服务端留存，按编号回放原编号；重试不会把 G1 改成通过；
- 发布领用幂等且带复核来源，G1 不可领用。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8021/api"
PASS = 0
FAIL = 0


def call(method: str, path: str, body=None):
    url = BASE + path
    if "?" in path:
        sp = urllib.parse.urlsplit(url)
        url = sp._replace(query=urllib.parse.urlencode(
            urllib.parse.parse_qsl(sp.query))).geturl()
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def check(name: str, cond: bool, extra="") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def main() -> int:
    _, r1 = call("POST", "/merge_review", {"values": {
        "记录编号": "MR-G1", "候选组": "G1", "复核结论": "待裁决"}})
    _, r2 = call("POST", "/merge_review", {"values": {
        "记录编号": "MR-G2", "候选组": "G2", "复核结论": "待裁决"}})
    g1, g2 = r1["entry"]["id"], r2["entry"]["id"]

    merge_ids = {}
    for g in ("G1", "G2"):
        _, m = call("POST", "/golden_merge", {"values": {
            "合并任务": f"合并-{g}", "实体编码": "ENT-X", "候选组": g,
            "生还规则": "置信度最高", "合并结果": ""}})
        mid = m["entry"]["id"]
        call("POST", f"/golden_merge/{mid}/actions", {"action": "转人工"})
        merge_ids[g] = mid

    _, rej = call("POST", f"/merge_review/{g1}/actions",
                  {"action": "驳回记录", "reviewer": "李复核", "reason": "字段冲突"})
    check("G1 被另一复核员驳回", rej.get("ok") is True, rej)

    _, batch = call("POST", "/merge_review/bulk-approve", {
        "ids": [g1, g2], "groups": ["G1", "G2"],
        "reviewer": "王复核", "submit_id": "SUBMIT-G1G2"})
    by_group = {it["候选组"]: it for it in batch.get("items", [])}
    check("整组部分受理（非整组未受理）", batch.get("accepted") and batch.get("partial"), batch)
    check("G1 回执=已驳回/处置冲突",
          by_group.get("G1", {}).get("status") == "已驳回"
          and by_group["G1"].get("ok") is False, by_group.get("G1"))
    check("G2 回执=已通过且可领用",
          by_group.get("G2", {}).get("status") == "已通过"
          and by_group["G2"].get("claimable") is True, by_group.get("G2"))
    rr = by_group["G2"]["回执编号"]

    _, g2list = call("GET", "/golden_merge?候选组=G2")
    g2merge = [x for x in g2list["items"] if x["id"] == merge_ids["G2"]][0]
    check("G2 金记录合并已完成并配对回执",
          g2merge["status"] == "已合并" and g2merge.get("复核回执编号") == rr, g2merge)

    _, stored = call("GET", "/merge_review/batches/SUBMIT-G1G2")
    sb = {it["候选组"]: it for it in stored.get("items", [])}
    check("整组回执可按编号回放且 G2 原编号不变",
          stored.get("idempotent_replay") and sb.get("G2", {}).get("回执编号") == rr, stored)

    _, retry = call("POST", "/merge_review/batch-approve", {"ids": [g1, g2]})
    rb = {it["候选组"]: it for it in retry.get("items", [])}
    check("重试后 G2 回放原编号", rb.get("G2", {}).get("回执编号") == rr, rb.get("G2"))
    check("重试不会把 G1 改成通过",
          rb.get("G1", {}).get("status") == "已驳回" and rb["G1"].get("ok") is False,
          rb.get("G1"))

    _, claim = call("POST", "/golden_publish/claim", {"group": "G2"})
    pid = claim.get("publish_id")
    check("领用 G2 发布批次成功并带来源",
          claim.get("ok") and claim["entry"].get("复核回执编号") == rr, claim)
    _, claim_again = call("POST", "/golden_publish/claim", {"group": "G2"})
    check("重复领用幂等返回原批次",
          claim_again.get("publish_id") == pid and claim_again.get("idempotent_replay"), claim_again)
    _, claim_g1 = call("POST", "/golden_publish/claim", {"group": "G1"})
    check("G1 不具备领用资格", not claim_g1.get("ok"), claim_g1)

    print(f"\n{ PASS } passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

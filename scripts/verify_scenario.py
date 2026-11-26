"""服务层验收：勾选 G1/G2 整组提交 + G1 并发驳回 + 回执回放 + 发布领用。

直接对内存仓库构造场景，不依赖 HTTP：
    python3 scripts/verify_scenario.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/workspace/backend")

from app.services.golden_publish import GoldenPublishService  # noqa: E402
from app.services.merge_review import MergeReviewService, qualify_group  # noqa: E402
from app.store import store  # noqa: E402

review_svc = MergeReviewService()
publish_svc = GoldenPublishService()

# ---- 构造 G1/G2 待复核记录与冲突合并任务 ----
base_review_id = max(int(r["id"]) for r in store.rows("merge_review")) + 1
g1_id, g2_id = base_review_id, base_review_id + 1
for offset, (rid, group, no) in enumerate([
    (g1_id, "G1", "MR-G1"), (g2_id, "G2", "MR-G2"),
]):
    store.rows("merge_review").append({
        "id": rid, "status": "待复核", "pending": True, "abnormal": False,
        "记录编号": no, "候选组": group, "复核结论": "待裁决",
        "复核角色": "", "复核时间": "",
    })

base_merge_id = max(int(r["id"]) for r in store.rows("golden_merge")) + 1
for offset, group in enumerate(["G1", "G2"]):
    store.rows("golden_merge").append({
        "id": base_merge_id + offset, "status": "合并冲突", "pending": False,
        "abnormal": False, "合并任务": f"合并-{group}", "实体编码": "ENT-X",
        "候选组": group, "生还规则": "置信度最高", "合并结果": f"GR-{group}-OLD",
    })

# ---- 另一名复核员在整组受理前驳回 G1 ----
reject = review_svc.reject_record(g1_id, "李复核", "字段冲突")
assert reject["ok"], reject

# ---- 操作员勾选 G1、G2 并整组提交（显式 id，不取队首）----
batch = review_svc.submit_batch({
    "ids": [g1_id, g2_id], "reviewer": "王复核", "submit_id": "S-1"})
assert batch["accepted"] and batch["partial"], batch
items = {it["候选组"]: it for it in batch["items"]}
assert items["G1"]["status"] == "已驳回" and items["G1"]["ok"] is False, items["G1"]
assert items["G2"]["status"] == "已通过" and items["G2"]["claimable"], items["G2"]
rr = items["G2"]["回执编号"]
print(f"[1] 整组回执 {batch['batch_no']}：G1 处置冲突保留驳回，G2 通过 {rr} 可领用")

g2_merge = next(m for m in store.rows("golden_merge") if m["候选组"] == "G2")
assert g2_merge["status"] == "已合并" and g2_merge["复核回执编号"] == rr
g1_merge = next(m for m in store.rows("golden_merge") if m["候选组"] == "G1")
assert g1_merge["status"] == "合并冲突"
print("[2] G2 金记录合并已确认并与回执配对；G1 冲突态与驳回一致")

# ---- 丢失响应后按整组编号重新请求：原样回放 ----
replay = review_svc.get_batch("S-1")
rp = {it["候选组"]: it for it in replay["items"]}
assert replay["idempotent_replay"] and rp["G2"]["回执编号"] == rr
assert rp["G1"]["status"] == "已驳回"
print("[3] 按 S-1 回放整组回执，G2 原编号不变，G1 仍驳回")

# ---- 不带提交编号重试整组：状态幂等，G1 不被改成通过 ----
retry = review_svc.submit_batch({"ids": [g1_id, g2_id]})
rt = {it["候选组"]: it for it in retry["items"]}
assert rt["G2"]["回执编号"] == rr and rt["G2"].get("idempotent_replay")
assert rt["G1"]["status"] == "已驳回" and rt["G1"]["ok"] is False
print("[4] 重试只回放 G2 原编号；驳回的 G1 未被改成通过")

# ---- 空选择不得消费队首待复核 ----
pending_before = sum(1 for r in store.rows("merge_review") if r["status"] == "待复核")
empty = review_svc.submit_batch({"max_count": 5})
pending_after = sum(1 for r in store.rows("merge_review") if r["status"] == "待复核")
assert not empty["ok"] and empty["code"] == "NO_SELECTION"
assert pending_before == pending_after
print("[5] 未勾选时拒绝受理，队列最前面的待复核记录未被替代处理")

# ---- 金记录合并读取回执交付资格；发布入口领用并追溯 ----
qual = qualify_group("G2")
assert qual["claimable"] and qual["deliverable"], qual
qual_g1 = qualify_group("G1")
assert not qual_g1["claimable"] and qual_g1["qualification"] == "rejected"
claim = publish_svc.claim_artifact(group="G2", submit_id="S-1")
assert claim["ok"] and claim["entry"]["复核回执编号"] == rr, claim
pid = claim["publish_id"]
again = publish_svc.claim_artifact(group="G2")
assert again["publish_id"] == pid and again["idempotent_replay"]
bad = publish_svc.claim_artifact(group="G1")
assert not bad["ok"] and bad["code"] == "NOT_CLAIMABLE"
print(f"[6] 发布入口领到批次 {claim['entry']['发布批次']}（id={pid}），"
      f"来源={claim['entry']['复核来源']}；重复领用幂等；G1 被资格拦截")

print("\n全部服务层验收断言通过 ✅")

"""金记录发布领域服务：管理金记录版本的发布批次、版本标识、扇出分发与回滚衔接，完成入库动作。

数据链路位置：主数据发布层，负责消费合并产物，把发布版本
扇出给订阅方并衔接版本回滚任务。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GoldenPublishService(BaseModuleService):
    MODULE = "golden_publish"
    ENTITY = "发布批次"
    OPERATION_TERM = "入库"
    LIST_FIELDS = ["发布批次", "实体编码", "金记录数", "发布时间", "版本标识"]
    REQUIRED_FIELDS = ["发布批次", "实体编码", "金记录数"]
    STATUS_ORDER = ["待发布", "已发布", "已回滚"]
    ACTION_RULES = {"发布批次": "已发布", "回滚批次": "已回滚"}
    NEGATIVE_ACTIONS = ["回滚批次"]

    # ---- 业务扩展：金记录发布与分发衔接 ----

    def release_version(self, entry_id: int) -> dict[str, Any]:
        """发布金记录版本，写发布时间与版本标识。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待发布":
            return {"ok": False, "message": "发布批次不在待发布状态"}
        now = datetime.now(timezone.utc).isoformat()
        version = f"pub-v{entry_id}-{now[:10]}"
        entry["发布时间"] = now
        entry["版本标识"] = version
        entry["status"] = "已发布"
        entry["pending"] = False
        return {"ok": True, "version": version, "released_at": now}

    def fanout_to_subscribers(self, entry_id: int) -> list[int]:
        """把已发布版本扇出给全部生效订阅方，生成分发批次。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已发布":
            return []
        tasks = store.rows("dist_task")
        created: list[int] = []
        for sub in store.rows("subscriber_mgr"):
            if sub.get("status") != "已生效":
                continue
            task_id = max((int(r.get("id", 0)) for r in tasks), default=0) + 1
            tasks.append({
                "id": task_id,
                "分发批次": f"dist-{entry_id}-{task_id}",
                "订阅方": sub.get("订阅方标识", ""),
                "记录范围": f"版本 {entry.get('版本标识', '')}",
                "分发状态": "排队中",
                "回执状态": "未回收",
                "status": "排队中",
                "pending": True,
                "abnormal": False,
            })
            created.append(task_id)
        return created

    def rollback_version(self, entry_id: int, reason: str) -> dict[str, Any]:
        """回滚发布版本并触发版本回滚任务。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已发布":
            return {"ok": False, "message": "批次未发布，无法回滚"}
        entry["status"] = "已回滚"
        entry["abnormal"] = True
        rollbacks = store.rows("version_rollback")
        rb_id = max((int(r.get("id", 0)) for r in rollbacks), default=0) + 1
        rollbacks.append({
            "id": rb_id,
            "回滚任务": f"rb-{entry_id}-{rb_id}",
            "目标版本": entry.get("版本标识", ""),
            "回滚原因": reason,
            "执行状态": "待执行",
            "影响订阅方": "",
            "status": "待执行",
            "pending": True,
            "abnormal": True,
        })
        return {"ok": True, "rollback_id": rb_id, "message": "回滚任务已创建"}

    def consume_merge_output(self, entry_id: int) -> list[dict[str, Any]]:
        """读取合并模块产出的金记录，作为发布输入。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        return [m for m in store.rows("golden_merge")
                if m.get("实体编码") == entry.get("实体编码") and m.get("status") == "已合并"]

    # ---- 复核回执驱动的发布领用：只领取有有效通过确认的实际产物 ----

    def ensure_batch_for_group(
        self,
        group: str,
        review: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """复核通过后幂等预登记同候选组的待发布批次（尚未领用）。"""
        for existing in store.rows(self.MODULE):
            if str(existing.get("候选组", "")) == group and existing.get("status") != "已回滚":
                return existing
        qual: dict[str, Any] | None = None
        if review is None:
            from app.services.merge_review import qualify_group
            qual = qualify_group(group)
        publishes = store.rows(self.MODULE)
        publish_id = max((int(r.get("id", 0)) for r in publishes), default=0) + 1
        entity_code = (qual or {}).get("实体编码") or (review or {}).get("实体编码", "")
        receipt_no = (review or {}).get("回执编号") or (qual or {}).get("回执编号", "")
        confirmation_no = (review or {}).get("确认编号") or (qual or {}).get("确认编号", "")
        record_no = (review or {}).get("记录编号", "") or (qual or {}).get("记录编号", "")
        row = {
            "id": publish_id,
            "发布批次": f"pub-{group}-{publish_id}",
            "实体编码": entity_code,
            "金记录数": "1",
            "发布时间": _now_iso(),
            "版本标识": f"v{publish_id}",
            "status": "待发布",
            "pending": True,
            "abnormal": False,
            "候选组": group,
            "group": group,
            "金记录标识": (qual or {}).get("golden_id", ""),
            "merge_id": (qual or {}).get("merge_id"),
            "复核记录id": (review or {}).get("id") or (qual or {}).get("review_id"),
            "复核记录编号": record_no,
            "review_no": record_no,
            "复核回执编号": receipt_no,
            "receipt_no": receipt_no,
            "复核确认编号": confirmation_no,
            "confirmation_no": confirmation_no,
            "复核来源": f"合并复核队列/{record_no}（{receipt_no}）" if receipt_no else "合并复核队列",
            "source_module": "merge_review",
            "claimed": False,
            "已领用": False,
            "领用状态": "待领用",
        }
        publishes.append(row)
        return row

    def claim_existing(self, entry_id: int, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """发布列表中对某个已存在批次行执行领用（可由 body 补充候选组/回执）。"""
        body = body or {}
        row = store.find(self.MODULE, entry_id)
        if row is None:
            return {"ok": False, "code": "BATCH_NOT_FOUND",
                    "message": f"发布批次 {entry_id} 不存在"}
        group = body.get("group") or body.get("候选组") or row.get("候选组")
        if not group and body.get("receipt_no"):
            receipt = body["receipt_no"]
            for review in store.rows("merge_review"):
                if review.get("回执编号") == receipt:
                    group = review.get("候选组")
                    break
        if not group:
            return {"ok": False, "code": "SOURCE_REQUIRED",
                    "message": "该批次尚未关联候选组或复核回执，无法领取复核来源记录"}
        result = self.claim_artifact(group=str(group), receipt_no=body.get("receipt_no"))
        if result.get("ok") and result.get("publish_id") != entry_id:
            row.setdefault("候选组", group)
            row["claimed"] = True
            row["已领用"] = True
            row["领用状态"] = "已领用"
            row["领用时间"] = _now_iso()
            result["publish_id"] = entry_id
            result["entry"] = row
        return result

    def list_claimable(self) -> list[dict[str, Any]]:
        """列出所有持有有效复核通过确认、尚可领用发布批次的候选组产物。"""
        from app.services.merge_review import qualify_group

        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for merge in store.rows("golden_merge"):
            group = str(merge.get("候选组", ""))
            if not group or group in seen:
                continue
            qual = qualify_group(group)
            if qual["claimable"]:
                seen.add(group)
                pb = qual.get("publish_batch") or {}
                result.append({
                    "候选组": group,
                    "group": group,
                    "实体编码": qual["实体编码"],
                    "金记录标识": qual["golden_id"],
                    "merge_id": qual["merge_id"],
                    "receipt_no": qual["receipt_no"],
                    "回执编号": qual["回执编号"],
                    "confirmation_no": qual["confirmation_no"],
                    "确认编号": qual["确认编号"],
                    "记录编号": qual["记录编号"],
                    "claimed": bool(pb.get("claimed")),
                    "已领用": bool(pb.get("claimed")),
                    "publish_id": qual["publish_id"],
                    "publish_batch_no": qual["publish_batch_no"],
                })
        return result

    def claim_artifact(
        self,
        *,
        group: str | None = None,
        receipt_no: str | None = None,
        merge_id: int | None = None,
        submit_id: str | None = None,
    ) -> dict[str, Any]:
        """按候选组 / 回执编号 / 合并任务领用发布批次（幂等）。

        资格完全以服务端 ``qualify_group`` 为准：只有拿到有效复核通过确认、
        金记录合并实际完成的候选组才能领到批次，并把复核来源写入批次以便追溯。
        重复领用返回原批次与原编号，不创建重复批次。
        """
        from app.services.merge_review import qualify_group

        # 仅凭回执编号也能定位候选组
        if not group and receipt_no:
            for review in store.rows("merge_review"):
                if review.get("回执编号") == receipt_no or review.get("receipt_no") == receipt_no:
                    group = str(review.get("候选组", ""))
                    break
        if not group and merge_id is not None:
            merge = store.find("golden_merge", int(merge_id))
            if merge is not None:
                group = str(merge.get("候选组", ""))

        group = str(group or "").strip()
        if not group:
            return {"ok": False, "code": "GROUP_REQUIRED",
                    "message": "请提供候选组、复核回执编号或合并任务，再领用发布批次"}

        qual = qualify_group(group)
        if not qual["claimable"]:
            return {
                "ok": False,
                "code": "NOT_CLAIMABLE",
                "message": f"{group} 暂不具备发布领用资格：{qual['reason']}",
                "qualification": qual,
            }

        # 幂等：同组已有未回滚批次（可能是通过时预登记的待领用批次），领用或回放。
        existing = next(
            (p for p in store.rows(self.MODULE)
             if str(p.get("候选组", "")) == group and p.get("status") != "已回滚"),
            None,
        )
        if existing is not None:
            if not existing.get("claimed"):
                existing["claimed"] = True
                existing["已领用"] = True
                existing["领用状态"] = "已领用"
                existing["领用时间"] = _now_iso()
                if submit_id:
                    existing["整组回执编号"] = submit_id
                return {
                    "ok": True,
                    "idempotent_replay": False,
                    "message": f"已领用 {group} 的发布批次 {existing.get('发布批次', '')}，可发布",
                    "publish_id": existing.get("id"),
                    "entry": existing,
                    "batch": existing,
                    "发布批次": existing.get("发布批次", ""),
                    "trace": self._trace(existing, qual),
                    "qualification": qual,
                }
            return {
                "ok": True,
                "idempotent_replay": True,
                "replayed": True,
                "message": f"{group} 的发布批次已领用，返回原批次编号",
                "publish_id": existing.get("id"),
                "entry": existing,
                "batch": existing,
                "发布批次": existing.get("发布批次", ""),
                "trace": self._trace(existing, qual),
                "qualification": qual,
            }

        publishes = store.rows(self.MODULE)
        publish_id = max((int(r.get("id", 0)) for r in publishes), default=0) + 1
        entity_code = qual.get("实体编码") or ""
        batch_no = f"pub-{group}-{publish_id}"
        row = {
            "id": publish_id,
            "发布批次": batch_no,
            "实体编码": entity_code,
            "金记录数": "1",
            "发布时间": _now_iso(),
            "版本标识": f"v{publish_id}",
            "status": "待发布",
            "pending": True,
            "abnormal": False,
            # ---- 跨页面追溯与领用资格字段 ----
            "候选组": group,
            "group": group,
            "金记录标识": qual.get("golden_id", ""),
            "merge_id": qual.get("merge_id"),
            "复核记录id": qual.get("review_id"),
            "复核记录编号": qual.get("记录编号", ""),
            "review_no": qual.get("记录编号", ""),
            "复核回执编号": qual.get("回执编号", ""),
            "receipt_no": qual.get("回执编号", ""),
            "复核确认编号": qual.get("确认编号", ""),
            "confirmation_no": qual.get("确认编号", ""),
            "复核来源": f"合并复核队列/{qual.get('记录编号', '')}（{qual.get('回执编号', '')}）",
            "source_module": "merge_review",
            "整组回执编号": submit_id or "",
            "claimed": True,
            "已领用": True,
            "领用时间": _now_iso(),
        }
        publishes.append(row)
        return {
            "ok": True,
            "idempotent_replay": False,
            "message": f"已领用 {group} 的发布批次 {batch_no}，可核对复核来源后发布",
            "publish_id": publish_id,
            "entry": row,
            "batch": row,
            "发布批次": batch_no,
            "trace": self._trace(row, qual),
            "qualification": qual,
        }

    @staticmethod
    def _trace(row: dict[str, Any], qual: dict[str, Any]) -> dict[str, Any]:
        return {
            "候选组": row.get("候选组", ""),
            "复核记录编号": row.get("复核记录编号", ""),
            "复核回执编号": row.get("复核回执编号", ""),
            "复核确认编号": row.get("复核确认编号", ""),
            "金记录标识": row.get("金记录标识", ""),
            "merge_id": row.get("merge_id"),
            "review_id": qual.get("review_id"),
            "来源页面": f"/merge_review?group={row.get('候选组', '')}",
        }

    def emit_stats_snapshot(self, entry_id: int) -> int:
        """发布完成后向治理看板输黄金记录数快照。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return 0
        stats = store.rows("stats_overview")
        stat_id = max((int(r.get("id", 0)) for r in stats), default=0) + 1
        stats.append({
            "id": stat_id,
            "统计时间": datetime.now(timezone.utc).isoformat(),
            "实体编码": entry.get("实体编码", ""),
            "金记录数": str(entry.get("金记录数", "0")),
            "重复率": "0%",
            "分发延迟": "0",
            "status": "正常",
            "pending": False,
            "abnormal": False,
        })
        return stat_id

    def register_publish_lineage(self, entry_id: int) -> str | None:
        """登记发布批次到分发模块的血缘边。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        edges = store.rows("lineage_graph")
        edge_id = max((int(r.get("id", 0)) for r in edges), default=0) + 1
        edges.append({
            "id": edge_id,
            "血缘边标识": f"edge-pub-{edge_id}",
            "上游节点": entry.get("发布批次", ""),
            "下游节点": "dist_task",
            "变换规则": "版本分发",
            "登记时间": datetime.now(timezone.utc).isoformat(),
            "status": "已登记",
            "pending": False,
            "abnormal": False,
        })
        return f"edge-pub-{edge_id}"

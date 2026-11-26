"""合并复核队列领域服务：管理人工裁决合并冲突候选组的复核记录、结论回写与批量办结。

数据链路位置：人工治理环节，负责消费合并冲突任务，
把裁决结论回写给合并任务并派发重新检测。

跨页面批量通过流程（cc10051 复核批次修复）：
- 批量提交只处理调用方显式给出的复核记录 id / 候选组，绝不取队列最前 N 条；
- 每条申请独立处置并出具逐条回执：通过的回写金记录合并并配对确认编号，
  已被其他复核员驳回的返回“处置冲突”，原驳回结论保留；
- 整组回执按提交编号在服务端留存，丢失响应后可按编号回放；
  已成功条目重复请求只回放原回执编号，驳回条目不会被重试改成通过；
- 金记录合并 / 金记录发布通过 ``qualify_group`` 读取有效通过确认，
  按服务端实际领用资格交付产物。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "是"}


def qualify_group(group: str | None, *, reconcile: bool = True) -> dict[str, Any]:
    """按候选组读取复核回执，给出金记录合并的配对确认与实际领用资格。

    这是金记录合并页 / 发布入口共享的唯一资格口径：
    必须存在“已通过且带回执编号”的复核确认，并且对应金记录合并任务
    已经是“已合并”，才允许领用发布批次。

    ``reconcile=True`` 时会自愈历史脏状态：复核已通过、金记录却仍卡在
    “合并冲突”的，读取回执后补做配对确认，交付有效结果。
    """
    group = str(group or "").strip()
    reviews = [r for r in store.rows("merge_review") if str(r.get("候选组", "")) == group]
    approved = [
        r for r in reviews
        if r.get("status") == "已通过" and (r.get("回执编号") or r.get("receipt_no"))
    ]
    rejected = [r for r in reviews if r.get("status") == "已驳回"]
    approved.sort(key=lambda r: int(r.get("id", 0)))
    rejected.sort(key=lambda r: int(r.get("id", 0)))
    review = approved[-1] if approved else None
    rejection = rejected[-1] if rejected else None

    merges = [m for m in store.rows("golden_merge") if str(m.get("候选组", "")) == group]
    merges.sort(key=lambda m: int(m.get("id", 0)))
    merge = merges[-1] if merges else None

    reconciled = False
    if review is not None and merge is not None:
        receipt_no = review.get("回执编号") or review.get("receipt_no")
        confirmation_no = review.get("确认编号") or review.get("confirmation_no")
        if merge.get("status") in ("合并冲突", "待合并") and reconcile:
            # 读取有效通过回执后补做金记录确认，修复“复核已通过、合并卡冲突”。
            merge["status"] = "已合并"
            merge["pending"] = False
            merge["abnormal"] = False
            if not merge.get("合并结果") or merge.get("合并结果") == merge.get("候选组"):
                merge["合并结果"] = f"GR-{group}-R"
            merge.setdefault("复核回执编号", receipt_no)
            merge["复核回执编号"] = receipt_no
            merge["复核确认编号"] = confirmation_no
            merge["复核记录id"] = review.get("id")
            merge["复核记录编号"] = review.get("记录编号", "")
            merge["复核通过时间"] = review.get("复核时间", _now())
            merge["确认状态"] = "复核通过已确认"
            reconciled = True
        elif merge.get("status") == "已合并":
            merge.setdefault("复核回执编号", receipt_no)
            merge.setdefault("复核确认编号", confirmation_no)
            merge.setdefault("复核记录id", review.get("id"))
            merge.setdefault("复核记录编号", review.get("记录编号", ""))

    merged_ok = merge is not None and merge.get("status") == "已合并"
    has_valid_approval = review is not None
    claimable = bool(has_valid_approval and merged_ok)

    if claimable:
        qualification = "ready"
        reason = ""
        label = "可交付·可领用发布批次"
    elif rejection is not None and not approved:
        qualification = "rejected"
        reason = "该候选组已被复核驳回，存在处置冲突，不能领用发布批次"
        label = "已驳回·不可领用"
    elif approved and not merged_ok:
        qualification = "merge_pending"
        reason = "已有通过回执，但金记录合并尚未确认完成"
        label = "合并确认中·暂不可领用"
    else:
        qualification = "pending"
        reason = "尚无有效的复核通过确认"
        label = "待复核·暂不可领用"

    # 是否已被发布入口领用（存在同组未回滚的发布批次）
    publish_batch = None
    for pub in store.rows("golden_publish"):
        if str(pub.get("候选组", "")) == group and pub.get("status") != "已回滚":
            publish_batch = pub
            break

    return {
        "group": group,
        "候选组": group,
        "claimable": claimable,
        "可领用": claimable,
        "qualification": qualification,
        "领用资格": label,
        "reason": reason,
        "message": reason,
        "reconciled": reconciled,
        "review_id": review.get("id") if review else None,
        "记录编号": (review or {}).get("记录编号", ""),
        "review_no": (review or {}).get("记录编号", ""),
        "receipt_no": (review or {}).get("回执编号", ""),
        "回执编号": (review or {}).get("回执编号", ""),
        "confirmation_no": (review or {}).get("确认编号", ""),
        "确认编号": (review or {}).get("确认编号", ""),
        "review_status": (review or {}).get("status", ""),
        "reject_review_id": rejection.get("id") if rejection else None,
        "驳回记录编号": (rejection or {}).get("记录编号", ""),
        "驳回原因": (rejection or {}).get("复核结论", ""),
        "merge_id": merge.get("id") if merge else None,
        "merge_status": (merge or {}).get("status", ""),
        "合并状态": (merge or {}).get("status", ""),
        "golden_id": (merge or {}).get("合并结果", ""),
        "合并结果": (merge or {}).get("合并结果", ""),
        "实体编码": (merge or {}).get("实体编码", ""),
        "publish_id": publish_batch.get("id") if publish_batch else None,
        "publish_batch_no": (publish_batch or {}).get("发布批次", ""),
        "claimed": bool((publish_batch or {}).get("claimed")),
        "已领用": bool((publish_batch or {}).get("claimed")),
        "publish_batch": publish_batch,
        "deliverable": {
            "候选组": group,
            "金记录标识": (merge or {}).get("合并结果", ""),
            "实体编码": (merge or {}).get("实体编码", ""),
            "merge_id": merge.get("id") if merge else None,
            "receipt_no": (review or {}).get("回执编号", ""),
            "confirmation_no": (review or {}).get("确认编号", ""),
        } if claimable else None,
    }


class MergeReviewService(BaseModuleService):
    MODULE = "merge_review"
    ENTITY = "复核记录"
    OPERATION_TERM = "合并"
    LIST_FIELDS = ["记录编号", "候选组", "复核结论", "复核角色", "复核时间"]
    REQUIRED_FIELDS = ["记录编号", "候选组", "复核结论"]
    STATUS_ORDER = ["待复核", "已通过", "已驳回"]
    ACTION_RULES = {"通过记录": "已通过", "驳回记录": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回记录"]

    def __init__(self) -> None:
        # 整组回执留存：batch_no / submit_id -> receipt dict
        self._batches: dict[str, dict[str, Any]] = {}
        self._batch_seq = 0

    # ---- 单条动作（通用 /actions 入口也必须走真实领域逻辑）----

    def run_action(
        self,
        entry_id: int,
        action: str,
        payload: Any | None = None,
        **_: Any,
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        reviewer = (
            getattr(payload, "reviewer", None)
            or getattr(payload, "operator", None)
            or "数据工程组"
        )
        remark = getattr(payload, "remark", None)
        reason = getattr(payload, "reason", None) or remark or "人工复核驳回"

        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档", {"ok": False}

        if action == "通过记录":
            result = self.approve_record(entry_id, str(reviewer))
            if not result.get("ok"):
                return entry, str(result.get("message")), {"ok": False, **result}
            extra = {k: v for k, v in result.items() if k != "ok"}
            return entry, f"复核 {entry.get('记录编号', entry_id)} 已通过，金记录合并已确认", extra

        if action == "驳回记录":
            result = self.reject_record(entry_id, str(reviewer), str(reason))
            if not result.get("ok"):
                return entry, str(result.get("message")), {"ok": False, **result}
            extra = {k: v for k, v in result.items() if k != "ok"}
            return entry, f"复核 {entry.get('记录编号', entry_id)} 已驳回", extra

        # 其余动作沿用通用状态流转
        target = self.ACTION_RULES.get(action)
        if target is None:
            return None, f"动作「{action}」不属于{self.MODULE}可执行范围", None
        entry["status"] = target
        entry["pending"] = target != self.STATUS_ORDER[-1]
        entry["abnormal"] = action in self.NEGATIVE_ACTIONS
        return entry, f"{self.ENTITY}已{action}", None

    # ---- 业务扩展：人工复核与合并回写 ----

    def approve_record(self, entry_id: int, reviewer: str) -> dict[str, Any]:
        """通过复核并把结论回写合并任务，出具稳定的复核回执编号。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "复核记录不存在"}
        if entry.get("status") != "待复核":
            # 已办结记录不能被重试改成通过；已通过的回放原回执。
            if entry.get("status") == "已通过":
                item = self._replay_item(entry)
                return {
                    "ok": True,
                    "idempotent_replay": True,
                    "replayed": True,
                    "message": "该记录此前已通过，回放原回执编号",
                    **{k: v for k, v in item.items() if k not in {"ok", "message"}},
                }
            return {
                "ok": False,
                "conflict": True,
                "code": "DISPOSITION_CONFLICT",
                "message": f"记录当前为{entry.get('status')}，存在处置冲突，不能通过",
            }

        receipt_no = str(entry.get("回执编号") or f"RR-{int(entry['id']):04d}")
        confirmation_no = str(entry.get("确认编号") or f"CF-{int(entry['id']):04d}")
        entry["status"] = "已通过"
        entry["复核结论"] = "确认合并"
        entry["复核角色"] = reviewer
        entry["复核时间"] = _now()
        entry["pending"] = False
        entry["abnormal"] = False
        entry["回执编号"] = receipt_no
        entry["receipt_no"] = receipt_no
        entry["确认编号"] = confirmation_no
        entry["confirmation_no"] = confirmation_no

        group = entry.get("候选组", "")
        merge_ids = self._pair_merge(group, entry, receipt_no, confirmation_no)
        qualification = qualify_group(group)
        return {
            "ok": True,
            "group": group,
            "候选组": group,
            "reviewer": reviewer,
            "id": entry["id"],
            "记录编号": entry.get("记录编号", ""),
            "receipt_no": receipt_no,
            "回执编号": receipt_no,
            "confirmation_no": confirmation_no,
            "确认编号": confirmation_no,
            "merge_ids": merge_ids,
            "claimable": qualification["claimable"],
            "可领用": qualification["claimable"],
            "qualification": qualification["qualification"],
        }

    def _pair_merge(
        self,
        group: str,
        review: dict[str, Any],
        receipt_no: str,
        confirmation_no: str,
    ) -> list[int]:
        """把通过确认成对回写到同候选组的金记录合并任务；缺失时补建产物。"""
        merge_ids: list[int] = []
        rows = store.rows("golden_merge")
        matched = [m for m in rows if m.get("候选组") == group]
        if not matched:
            merge_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            entity_code = review.get("实体编码") or f"ENT-{group}"
            rows.append({
                "id": merge_id,
                "status": "已合并",
                "pending": False,
                "abnormal": False,
                "合并任务": f"合并任务-{group}",
                "实体编码": entity_code,
                "候选组": group,
                "group": group,
                "生还规则": "置信度最高",
                "合并结果": f"GR-{group}-R",
                "golden_id": f"GR-{group}-R",
                "复核回执编号": receipt_no,
                "receipt_no": receipt_no,
                "复核确认编号": confirmation_no,
                "confirmation_no": confirmation_no,
                "paired": True,
                "复核记录id": review.get("id"),
                "复核记录编号": review.get("记录编号", ""),
                "review_no": review.get("记录编号", ""),
                "复核通过时间": review.get("复核时间", _now()),
                "确认状态": "复核通过已确认",
            })
            merge_ids.append(merge_id)
        else:
            for task in matched:
                if task.get("status") in ("合并冲突", "待合并"):
                    task["status"] = "已合并"
                    task["pending"] = False
                    task["abnormal"] = False
                    if not task.get("合并结果") or task.get("合并结果") == task.get("候选组"):
                        task["合并结果"] = f"GR-{group}-R"
                task["group"] = group
                task["golden_id"] = task.get("合并结果", "")
                task["复核回执编号"] = receipt_no
                task["receipt_no"] = receipt_no
                task["复核确认编号"] = confirmation_no
                task["confirmation_no"] = confirmation_no
                task["paired"] = True
                task["复核记录id"] = review.get("id")
                task["复核记录编号"] = review.get("记录编号", "")
                task["review_no"] = review.get("记录编号", "")
                task["复核通过时间"] = review.get("复核时间", _now())
                task["确认状态"] = "复核通过已确认"
                merge_ids.append(int(task["id"]))

        # 通过确认成立后，为该候选组预登记可领用的待发布批次（幂等），
        # 发布入口再凭“领用”动作正式领取并保留复核来源。
        try:
            from app.services.golden_publish import GoldenPublishService
            GoldenPublishService().ensure_batch_for_group(group, review=review)
        except Exception:  # noqa: BLE001 - 预登记失败不影响复核主流程
            pass
        return merge_ids

    def reject_record(self, entry_id: int, reviewer: str, reason: str) -> dict[str, Any]:
        """驳回复核并退回重复检测重排。已驳回记录保持原结论，不重复处置。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "复核记录不存在"}
        if entry.get("status") != "待复核":
            return {
                "ok": entry.get("status") == "已驳回",
                "idempotent_replay": entry.get("status") == "已驳回",
                "message": f"记录当前为{entry.get('status')}，驳回结论保留",
                "id": entry_id,
                "status": entry.get("status"),
            }
        entry["status"] = "已驳回"
        entry["复核结论"] = f"驳回: {reason}"
        entry["复核角色"] = reviewer
        entry["复核时间"] = _now()
        entry["abnormal"] = True
        entry["pending"] = False
        group = entry.get("候选组", "")
        batches = store.rows("dup_detect")
        batch_id = max((int(r.get("id", 0)) for r in batches), default=0) + 1
        batches.append({
            "id": batch_id,
            "检测批次": f"redetect-{group}-{batch_id}",
            "实体编码": entry.get("实体编码", ""),
            "候选组数": "0",
            "相似度算法": "编辑距离",
            "置信区间": "[0.90,1.0]",
            "status": "检测中",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "redetect_batch": batch_id, "id": entry_id, "status": "已驳回"}

    def consume_conflicts(self, entry_id: int) -> list[dict[str, Any]]:
        """读取合并冲突任务，生成本复核队列输入。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        group = entry.get("候选组", "")
        return [t for t in store.rows("golden_merge")
                if t.get("候选组") == group and t.get("status") == "合并冲突"]

    # ------------------------------------------------------------------
    # 批量勾选提交：只处理显式选中的 id / 候选组，逐条回执 + 整组留存
    # ------------------------------------------------------------------

    def _resolve_selection(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """把各种可能的勾选载荷归一为选中的复核行（保持顺序、去重）。"""
        selected_ids: list[int] = []
        selected_groups: list[str] = []

        # 顶层直接传 id 数组：[4, 5]
        if isinstance(payload.get("items"), list) and not payload.get("ids") \
                and all(isinstance(x, (int, str)) for x in payload["items"]):
            payload = {**payload, "ids": payload["items"]}

        def collect_id(value: Any) -> None:
            if value is None or value == "":
                return
            if isinstance(value, dict):
                value = value.get("id") or value.get("review_id") or value.get("entry_id")
            try:
                selected_ids.append(int(value))
            except (TypeError, ValueError):
                # 也允许直接传记录编号
                for row in store.rows(self.MODULE):
                    if str(row.get("记录编号", "")) == str(value):
                        selected_ids.append(int(row["id"]))
                        break

        for key in ("ids", "entry_ids", "review_ids", "selected_ids", "id_list",
                    "entity_ids", "record_ids"):
            for value in _as_list(payload.get(key)):
                collect_id(value)
        for key in ("id", "entry_id", "review_id"):
            if payload.get(key) is not None:
                collect_id(payload.get(key))

        for key in ("groups", "candidate_groups", "candidateGroups",
                    "selected_groups", "selectedGroups", "候选组列表", "候选组s"):
            for value in _as_list(payload.get(key)):
                if isinstance(value, dict):
                    selected_groups.append(str(value.get("候选组") or value.get("group") or ""))
                else:
                    selected_groups.append(str(value))
        if payload.get("group") or payload.get("候选组"):
            value = payload.get("group") or payload.get("候选组")
            for item in _as_list(value):
                selected_groups.append(str(item))

        # selected / selection / rows / records / targets / candidates
        # 可能是 id 数组，也可能是勾选对象数组
        for key in ("selected", "selection", "items", "rows", "records",
                    "review_rows", "selectedRows", "targets", "candidates", "data"):
            for value in _as_list(payload.get(key)):
                if isinstance(value, (int, str)):
                    if isinstance(value, int) or str(value).strip().isdigit():
                        collect_id(value)
                    else:
                        selected_groups.append(str(value))
                elif isinstance(value, dict):
                    if value.get("id") is not None:
                        collect_id(value.get("id"))
                    elif value.get("review_id") is not None:
                        collect_id(value.get("review_id"))
                    g = value.get("候选组") or value.get("group") or value.get("candidate_group")
                    if g:
                        selected_groups.append(str(g))

        chosen: list[dict[str, Any]] = []
        seen: set[int] = set()

        def add_row(row: dict[str, Any] | None) -> None:
            if row is None:
                return
            rid = int(row["id"])
            if rid not in seen:
                seen.add(rid)
                chosen.append(row)

        rows_by_id = {int(r["id"]): r for r in store.rows(self.MODULE)}
        for rid in selected_ids:
            add_row(rows_by_id.get(rid))
        for group in dict.fromkeys(g for g in selected_groups if g):
            for row in store.rows(self.MODULE):
                if str(row.get("候选组", "")) == group:
                    add_row(row)
        return chosen

    def _replay_item(self, row: dict[str, Any]) -> dict[str, Any]:
        """构造一条只回放原编号、不产生新副作用的条目回执。"""
        group = str(row.get("候选组", ""))
        qualification = qualify_group(group)
        status = str(row.get("status", ""))
        if status == "已通过":
            outcome, code, ok = "approved", "APPROVED", True
            state_text = "已通过（回放原回执编号，未重复处置）"
        elif status == "已驳回":
            outcome, code, ok = "conflict", "DISPOSITION_CONFLICT", False
            state_text = "已被驳回，处置冲突保留，不能改成通过"
        else:
            outcome, code, ok = "pending", "PENDING", False
            state_text = "仍在待复核"
        return {
            "ok": ok,
            "id": int(row["id"]),
            "review_id": int(row["id"]),
            "记录编号": row.get("记录编号", ""),
            "review_no": row.get("记录编号", ""),
            "候选组": group,
            "group": group,
            "status": status,
            "outcome": outcome,
            "code": code,
            "state_text": state_text,
            "message": state_text,
            "receipt_no": row.get("回执编号", ""),
            "回执编号": row.get("回执编号", ""),
            "confirmation_no": row.get("确认编号", ""),
            "确认编号": row.get("确认编号", ""),
            "reviewer": row.get("复核角色", ""),
            "复核角色": row.get("复核角色", ""),
            "claimable": qualification["claimable"] if status == "已通过" else False,
            "可领用": qualification["claimable"] if status == "已通过" else False,
            "qualification": qualification["qualification"],
            "golden_id": qualification["golden_id"],
            "合并结果": qualification["合并结果"],
            "merge_id": qualification["merge_id"],
            "publish_id": qualification["publish_id"],
            "publish_batch_no": qualification["publish_batch_no"],
        }

    def _process_one(
        self,
        row: dict[str, Any],
        reviewer: str,
        batch_no: str,
    ) -> dict[str, Any]:
        current = str(row.get("status", ""))
        if current == "待复核":
            result = self.approve_record(int(row["id"]), reviewer)
            if result.get("ok"):
                item = self._replay_item(row)
                item.update({
                    "outcome": "approved",
                    "code": "APPROVED",
                    "first_time": True,
                    "idempotent_replay": False,
                    "batch_no": batch_no,
                    "整组回执编号": batch_no,
                    "state_text": "本次提交已通过，金记录合并已确认",
                    "message": f"{row.get('候选组')} 已通过并配对金记录确认",
                })
                row["整组回执编号"] = batch_no
                return item
            # 并发情况下状态可能刚被别人改掉
            item = self._replay_item(row)
            item["message"] = result.get("message") or item["message"]
            return item

        # 已通过 / 已驳回：只回放当前服务端事实
        item = self._replay_item(row)
        item["idempotent_replay"] = current == "已通过"
        item["replayed"] = current == "已通过"
        item["batch_no"] = batch_no
        item["整组回执编号"] = batch_no
        if current == "已驳回":
            item["conflict"] = True
            item["message"] = (
                f"{row.get('候选组')} 在受理前已被其他复核员驳回"
                f"（{row.get('复核角色', '')}），同一组申请存在处置冲突；"
                "原驳回记录保留，本次不会改成通过"
            )
        return item

    def submit_batch(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """受理一次整组勾选提交，返回整组回执（含逐条结果），并在服务端留存。"""
        payload = dict(payload or {})

        submit_id = str(
            payload.get("submit_id")
            or payload.get("idempotency_key")
            or payload.get("batch_no")
            or payload.get("整组回执编号")
            or payload.get("batch_id")
            or ""
        ).strip()

        # 同编号整组重放：直接返回留存原件，不再处置任何条目。
        if submit_id and submit_id in self._batches:
            stored = self._batches[submit_id]
            replay = dict(stored)
            replay["idempotent_replay"] = True
            replay["replayed"] = True
            replay["message"] = "整组回执回放：成功条目保留原编号，驳回条目维持驳回"
            return replay

        chosen = self._resolve_selection(payload)

        reviewer = str(
            payload.get("reviewer")
            or payload.get("operator")
            or payload.get("复核角色")
            or "数据工程组"
        )

        self._batch_seq += 1
        batch_no = submit_id or f"BATCH-{self._batch_seq:04d}"

        if not chosen:
            receipt = {
                "ok": False,
                "accepted": False,
                "code": "NO_SELECTION",
                "batch_no": batch_no,
                "整组回执编号": batch_no,
                "submit_id": submit_id or None,
                "message": "未勾选任何复核记录或候选组；批量提交只处理操作员实际选中的条目",
                "total": 0,
                "approved_count": 0,
                "conflict_count": 0,
                "rejected_count": 0,
                "items": [],
                "receipts": [],
                "results": [],
                "claimable_groups": [],
            }
            if submit_id:
                self._batches[submit_id] = receipt
            return receipt

        items = [self._process_one(row, reviewer, batch_no) for row in chosen]
        approved = [it for it in items if it.get("outcome") == "approved"]
        conflicts = [it for it in items if it.get("outcome") == "conflict"]
        rejected = [it for it in items if it.get("status") == "已驳回"]
        claimable_groups = [it["候选组"] for it in items if it.get("claimable")]

        all_approved = len(approved) == len(items)
        receipt = {
            "ok": True,
            "accepted": True,
            "partial": bool(conflicts or rejected) and bool(approved),
            "all_approved": all_approved,
            "batch_no": batch_no,
            "整组回执编号": batch_no,
            "submit_id": submit_id or batch_no,
            "reviewer": reviewer,
            "submitted_at": _now(),
            "total": len(items),
            "approved_count": len(approved),
            "conflict_count": len(conflicts),
            "rejected_count": len(rejected),
            "success_count": len(approved),
            "failure_count": len(conflicts) + len(rejected),
            "approved_ids": [it["id"] for it in approved],
            "conflict_ids": [it["id"] for it in conflicts],
            "rejected_ids": [it["id"] for it in rejected],
            "approved_items": approved,
            "conflict_items": conflicts,
            "claimable_groups": claimable_groups,
            "可领用候选组": claimable_groups,
            "message": (
                f"整组受理 {len(items)} 条：通过 {len(approved)} 条，"
                f"处置冲突/驳回 {len(conflicts) or len(rejected)} 条；"
                + (f"{ '、'.join(claimable_groups) } 已有可领用结果" if claimable_groups
                   else "暂无可以领用的发布结果")
            ),
            "items": items,
            "receipts": items,
            "results": items,
            "data": items,
            "selected_ids": [int(r["id"]) for r in chosen],
            "selected_groups": [str(r.get("候选组", "")) for r in chosen],
        }
        self._batches[batch_no] = receipt
        if submit_id and submit_id != batch_no:
            self._batches[submit_id] = receipt
        return receipt

    # 旧入口保留为“按显式选择提交”，修复取队列最前 N 条的问题。
    def bulk_approve(
        self,
        reviewer: str | None = None,
        entry_ids: list[int] | int | None = None,
        groups: list[str] | None = None,
        max_count: int | None = None,
        submit_id: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        if isinstance(entry_ids, int):
            # 兼容旧的位置参数 bulk_approve(reviewer, max_count)：
            # 这是已废弃的“取前 N 条”口径，不能替代显式勾选，因此不自动选队首。
            max_count = entry_ids
            entry_ids = None
        payload: dict[str, Any] = {
            "reviewer": reviewer,
            "ids": entry_ids or extra.get("ids"),
            "groups": groups,
            "submit_id": submit_id,
        }
        payload.update({k: v for k, v in extra.items() if v is not None})
        result = self.submit_batch(payload)
        result["approved"] = result.get("approved_count", 0)
        return result

    def get_batch(self, batch_no: str) -> dict[str, Any] | None:
        stored = self._batches.get(str(batch_no))
        if stored is None:
            return None
        replay = dict(stored)
        replay["idempotent_replay"] = True
        replay["replayed"] = True
        replay["message"] = "按整组编号重新请求：成功条目回放原编号，驳回条目不改变结论"
        return replay

    def list_batches(self) -> list[dict[str, Any]]:
        return list(self._batches.values())

    def qualification(self, group: str) -> dict[str, Any]:
        return qualify_group(group)

    def stats_pending_by_role(self) -> dict[str, int]:
        """按复核角色统计待复核量，供容量排班。"""
        counter: dict[str, int] = {}
        for row in store.rows(self.MODULE):
            if row.get("status") == "待复核":
                role = row.get("复核角色", "未指派")
                counter[role] = counter.get(role, 0) + 1
        return counter

    def archive_reviewed(self, days: int) -> int:
        """归档已办结的复核记录。"""
        archived = 0
        for row in store.rows(self.MODULE):
            if row.get("status") in ("已通过", "已驳回"):
                row["归档"] = True
                row["归档天数"] = days
                archived += 1
        return archived

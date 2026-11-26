"""复核批次跨页面流程的领域路由。

通用资源路由只提供单条动作；这里承载：
- 合并复核：按显式勾选的 id/候选组整组提交、整组回执留存与回放、领用资格查询；
- 金记录合并：读取复核回执交付配对确认与实际领用资格、发起发布领用；
- 金记录发布：按回执/候选组幂等领用发布批次并追溯复核来源。

路径同时给出常见命名别名，固定路径统一在通配资源路由之前注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services import service_for
from app.services.merge_review import qualify_group

router = APIRouter(prefix="/api", tags=["复核批次跨页流程"])


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        data = {}
    if isinstance(data, list):
        return {"ids": data}
    return data if isinstance(data, dict) else {}


def _review_service():
    return service_for("merge_review")


def _publish_service():
    return service_for("golden_publish")


# ---------------------------------------------------------------------------
# 合并复核：整组勾选提交（多路径别名，同一套选择口径）
# ---------------------------------------------------------------------------

_BULK_PATHS = [
    "/merge_review/bulk-approve",
    "/merge_review/bulk_approve",
    "/merge_review/bulkApprove",
    "/merge_review/approve-batch",
    "/merge_review/batch-pass",
    "/merge_review/pass-batch",
    "/merge_review/batch-approve",
    "/merge_review/batch_approve",
    "/merge_review/batchApprove",
    "/merge_review/batch-submit",
    "/merge_review/submit-batch",
    "/merge_review/batch",
    "/merge_review/batches",
    "/merge_review/bulk",
    "/merge_review/batch/actions",
    "/merge_review/batch-actions",
    "/merge_review/reviews/batch-approve",
]


async def _submit_batch(request: Request) -> dict[str, Any]:
    payload = await _json_body(request)
    # 也允许 query / 请求头携带 submit_id / reviewer / 幂等键
    payload.setdefault("submit_id", request.query_params.get("submit_id"))
    payload.setdefault("reviewer", request.query_params.get("reviewer"))
    idem = (request.headers.get("idempotency-key")
            or request.headers.get("x-idempotency-key")
            or request.headers.get("x-submit-id"))
    if idem and not payload.get("submit_id"):
        payload["submit_id"] = idem
    action = str(payload.get("action") or payload.get("batch_action") or "通过记录")
    svc = _review_service()

    # 批量驳回（非主路径，保持与通过一致的逐条回执口径）
    if "驳回" in action:
        chosen = svc._resolve_selection(payload)  # noqa: SLF001 - 同领域编排
        reviewer = payload.get("reviewer") or payload.get("operator") or "数据工程组"
        reason = payload.get("reason") or payload.get("remark") or "整组驳回"
        items = []
        for row in chosen:
            res = svc.reject_record(int(row["id"]), str(reviewer), str(reason))
            items.append({
                "ok": bool(res.get("ok")),
                "id": int(row["id"]),
                "记录编号": row.get("记录编号", ""),
                "候选组": row.get("候选组", ""),
                "status": row.get("status"),
                "message": res.get("message", ""),
            })
        return {"ok": True, "accepted": True, "items": items, "receipts": items,
                "total": len(items), "message": f"整组驳回 {len(items)} 条"}

    return svc.submit_batch(payload)


for _path in _BULK_PATHS:
    router.add_api_route(_path, _submit_batch, methods=["POST"])


# ---------------------------------------------------------------------------
# 合并复核：整组回执回放 / 资格查询
# ---------------------------------------------------------------------------

@router.get("/merge_review/batches/{batch_no}")
def get_batch(batch_no: str) -> dict[str, Any]:
    receipt = _review_service().get_batch(batch_no)
    if receipt is None:
        return {"ok": False, "code": "BATCH_NOT_FOUND",
                "message": f"服务端没有整组回执 {batch_no}", "batch_no": batch_no}
    return receipt


@router.get("/merge_review/batch/{batch_no}")
def get_batch_alias(batch_no: str) -> dict[str, Any]:
    return get_batch(batch_no)


@router.get("/merge_review/receipts/{batch_no}")
def get_batch_receipt_alias(batch_no: str) -> dict[str, Any]:
    return get_batch(batch_no)


@router.get("/merge_review/batches/{batch_no}/receipt")
def get_batch_nested_receipt(batch_no: str) -> dict[str, Any]:
    return get_batch(batch_no)


@router.get("/merge_review/batch/{batch_no}/receipt")
def get_batch_nested_receipt_alias(batch_no: str) -> dict[str, Any]:
    return get_batch(batch_no)


@router.get("/merge_review/receipt")
def get_receipt_by_query(batch_no: str | None = None, submit_id: str | None = None,
                         no: str | None = None) -> dict[str, Any]:
    return get_batch_by_query(batch_no=batch_no or no, submit_id=submit_id)


@router.get("/merge_review/batch-receipt")
def get_batch_by_query(batch_no: str | None = None, submit_id: str | None = None) -> dict[str, Any]:
    key = batch_no or submit_id or ""
    receipt = _review_service().get_batch(key) if key else None
    if receipt is None:
        return {"ok": False, "code": "BATCH_NOT_FOUND",
                "message": "缺少可回放的整组回执编号", "batch_no": key}
    return receipt


@router.get("/merge_review/batches")
def list_batches() -> dict[str, Any]:
    items = _review_service().list_batches()
    return {"items": items, "total": len(items)}


@router.get("/merge_review/qualification")
def review_qualification(group: str | None = None, 候选组: str | None = None) -> dict[str, Any]:
    return qualify_group(group or 候选组 or "")


@router.get("/merge_review/qualify")
def review_qualify_alias(group: str | None = None, 候选组: str | None = None) -> dict[str, Any]:
    return review_qualification(group, 候选组)


@router.get("/merge_review/by-group/{group}")
def review_by_group(group: str) -> dict[str, Any]:
    return qualify_group(group)


# ---------------------------------------------------------------------------
# 金记录合并：配对确认 / 领用资格 / 发起领用
# ---------------------------------------------------------------------------

@router.get("/golden_merge/qualification")
def merge_qualification(group: str | None = None, 候选组: str | None = None,
                        receipt_no: str | None = None) -> dict[str, Any]:
    if not (group or 候选组) and receipt_no:
        from app.store import store
        for r in store.rows("merge_review"):
            if r.get("回执编号") == receipt_no:
                group = str(r.get("候选组", ""))
                break
    return qualify_group(group or 候选组 or "")


@router.get("/golden_merge/by-group/{group}")
def merge_by_group(group: str) -> dict[str, Any]:
    return qualify_group(group)


@router.get("/golden_merge/{entry_id}/confirmation")
def merge_confirmation(entry_id: int) -> dict[str, Any]:
    service = service_for("golden_merge")
    return service.review_confirmation(entry_id)


@router.get("/golden_merge/{entry_id}/qualification")
def merge_qualification_by_id(entry_id: int) -> dict[str, Any]:
    return merge_confirmation(entry_id)


@router.get("/golden_merge/{entry_id}/receipt")
def merge_receipt_by_id(entry_id: int) -> dict[str, Any]:
    return merge_confirmation(entry_id)


@router.get("/golden_merge/{entry_id}/review")
def merge_review_by_id(entry_id: int) -> dict[str, Any]:
    return merge_confirmation(entry_id)


@router.post("/golden_merge/{entry_id}/claim")
async def merge_claim(entry_id: int, request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    result = service_for("golden_merge").claim_publish(entry_id)
    if body.get("submit_id") and isinstance(result, dict):
        result.setdefault("submit_id", body["submit_id"])
    return result


@router.post("/golden_merge/{entry_id}/claim-publish")
async def merge_claim_alias(entry_id: int, request: Request) -> dict[str, Any]:
    return await merge_claim(entry_id, request)


# ---------------------------------------------------------------------------
# 金记录发布：可领用产物清单 + 按候选组/回执幂等领用
# ---------------------------------------------------------------------------

@router.get("/golden_publish/claimable")
def publish_claimable() -> dict[str, Any]:
    items = _publish_service().list_claimable()
    return {"items": items, "total": len(items)}


@router.get("/golden_publish/claimable-artifacts")
def publish_claimable_alias() -> dict[str, Any]:
    return publish_claimable()


_CLAIM_PATHS = [
    "/golden_publish/claim",
    "/golden_publish/claim-batch",
    "/golden_publish/claim_batch",
    "/golden_publish/receive",
]


async def _publish_claim(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    group = body.get("group") or body.get("候选组") or request.query_params.get("group")
    receipt_no = body.get("receipt_no") or body.get("回执编号")
    merge_id = body.get("merge_id") or body.get("id")
    try:
        merge_id = int(merge_id) if merge_id is not None and merge_id != "" else None
    except (TypeError, ValueError):
        merge_id = None
    return _publish_service().claim_artifact(
        group=group, receipt_no=receipt_no, merge_id=merge_id,
        submit_id=body.get("submit_id") or body.get("整组回执编号"))


for _path in _CLAIM_PATHS:
    router.add_api_route(_path, _publish_claim, methods=["POST"])


@router.post("/golden_publish/{entry_id}/claim")
async def publish_claim_by_id(entry_id: int, request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    return _publish_service().claim_existing(entry_id, body)


@router.post("/golden_publish/{entry_id}/receive")
async def publish_receive_by_id(entry_id: int, request: Request) -> dict[str, Any]:
    return await publish_claim_by_id(entry_id, request)


@router.get("/golden_publish/inbox")
def publish_inbox() -> dict[str, Any]:
    return publish_claimable()


@router.get("/golden_publish/claimable-records")
def publish_claimable_records() -> dict[str, Any]:
    return publish_claimable()

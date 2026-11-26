"""业务路由汇总：复核跨页领域路由优先注册，通用资源路由兜底。"""
from __future__ import annotations

from app.routers import resource, review_flow

# review_flow 含 /api/merge_review/bulk-approve、
# /api/golden_publish/claim 等固定路径，必须排在通配 /api/{module}
# 资源路由之前，否则会被动态路径抢先匹配。
ROUTERS = [review_flow, resource]

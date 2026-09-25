"""限电记录接口：维护限电事件，覆盖确认限电、确认恢复、提交申诉等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.curtail import CurtailService

router = APIRouter(prefix="/api/curtail", tags=["限电记录"])

service = CurtailService()

LIST_FIELDS = ["事件编号", "所属电站", "限电原因", "限电开始时间", "限电结束时间", "损失电量", "调度指令号", "限电状态"]
STATUSES = ["待确认", "已确认", "已恢复", "已申诉"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按事件编号检索"),
    status: str | None = Query(default=None, description="待确认、已确认、已恢复、已申诉"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按事件编号与状态过滤限电记录列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def entry_stats(
    keyword: str | None = Query(default=None, description="按事件编号检索"),
    status: str | None = Query(default=None, description="待确认、已确认、已恢复、已申诉"),
) -> dict[str, Any]:
    """合计卡片：与列表同一筛选口径，操作后与列表一起刷新。"""
    return service.stats(keyword=keyword, status=status)


@router.get("/export")
def export_entries(
    keyword: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """导出限电记录清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(keyword=keyword, status=status, page=1, size=10000)
    return {"module": "curtail", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条限电事件明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"限电事件 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条限电事件，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="限电事件已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: dict[str, Any] = Body(default_factory=dict)) -> ActionResult:
    """对单条限电事件执行确认限电、确认恢复、提交申诉；不允许的动作会被拦下并说明原因。

    action 兼容直接放在请求体或 values 里两种提交方式；重复提交同一动作只算一次，
    已恢复的事件不能再退回待确认。
    """
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    action = str(payload.get("action") or values.get("action") or "").strip()
    remark = payload.get("remark")
    entry, message = service.run_action(entry_id, action, remark=remark)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

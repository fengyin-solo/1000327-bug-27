"""限电记录业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "curtail"
REQUIRED_FIELDS = ["事件编号", "所属电站", "限电原因"]
STATUS_ORDER = ["待确认", "已确认", "已恢复", "已申诉"]
ACTION_RULES = {"确认限电": "已确认", "确认恢复": "已恢复", "提交申诉": "已申诉"}
NEGATIVE_ACTIONS: list[str] = []

# 各动作允许的来源状态：已恢复是终态，不允许再退回待确认/已确认。
# 提交申诉沿用老流程，对来源状态不做限制。
ACTION_SOURCES: dict[str, set[str] | None] = {
    "确认限电": {"待确认"},
    "确认恢复": {"已确认"},
    "提交申诉": None,
}
RECOVER_ACTION = "确认恢复"
RECOVERED_STATUS = "已恢复"
# 还在确认链路上、需要继续处理的状态
OPEN_STATUSES = {"待确认", "已确认"}
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


class CurtailService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filtered_rows(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def summarize(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """统计卡片与列表共用同一套筛选口径，保证合计数和列表对得上。"""
        rows = self._filtered_rows(keyword=keyword, status=status)
        today = date.today().isoformat()
        today_count = sum(
            1 for row in rows if str(row.get("限电开始时间", "")).startswith(today)
        )
        loss_total = round(sum(self._loss_value(row) for row in rows), 2)
        appeal_pending = sum(1 for row in rows if row.get("status") in OPEN_STATUSES)
        return [
            {"label": "今日限电次数", "value": today_count},
            {"label": "损失电量合计", "value": loss_total},
            {"label": "待申诉事件", "value": appeal_pending},
        ]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["限电状态"] = STATUS_ORDER[0]
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"限电事件 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于限电记录可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        current = str(entry.get("status") or STATUS_ORDER[0])
        # 确认恢复是终态动作：重复提交只算一次，不改状态也不覆盖首次恢复时间。
        if action == RECOVER_ACTION and current == RECOVERED_STATUS:
            return entry, "限电事件已恢复，重复提交不再重复处理"
        sources = ACTION_SOURCES.get(action)
        if sources is not None and current not in sources:
            return None, f"限电事件当前状态为「{current}」，不能执行{action}"

        entry["status"] = target
        entry["pending"] = target in OPEN_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        # 限电状态字段与状态机保持同源，列表与详情就不会各说各话。
        entry["限电状态"] = target
        if action == RECOVER_ACTION:
            entry["恢复时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return entry, f"限电事件已{action}"

    def _filtered_rows(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("事件编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    @staticmethod
    def _loss_value(row: dict[str, Any]) -> float:
        raw = row.get("损失电量")
        if isinstance(raw, bool):
            return 0.0
        if isinstance(raw, (int, float)):
            return float(raw)
        match = _NUMBER_RE.search(str(raw or ""))
        return float(match.group()) if match else 0.0

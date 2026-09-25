"""限电记录业务规则：状态流转、字段校验、筛选口径与合计口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "curtail"
REQUIRED_FIELDS = ["事件编号", "所属电站", "限电原因"]
LIST_FIELDS = ["事件编号", "所属电站", "限电原因", "限电开始时间", "限电结束时间", "损失电量", "调度指令号"]
STATUS_ORDER = ["待确认", "已确认", "已恢复", "已申诉"]
# 仍需跟进（可确认、可恢复）的状态；已恢复、已申诉均为办结态
PENDING_STATUSES = ["待确认", "已确认"]
ACTION_RULES = {"确认限电": "已确认", "确认恢复": "已恢复", "提交申诉": "已申诉"}
# 早期脏数据里错位混入的时段标识，不属于限电事件字段，列表与详情统一清掉
STRAY_FIELDS = ["时段标识", "时段"]


class CurtailService:
    def __init__(self) -> None:
        # 启动时规整一次：同一事件重复登记的行合并、错位字段剔除、状态列与后台状态对齐
        self._normalize()

    # ------------------------------------------------------------------
    # 数据规整
    # ------------------------------------------------------------------
    def _normalize(self) -> None:
        rows = store.rows(MODULE)
        canonical: dict[str, dict[str, Any]] = {}
        for row in rows:
            for stray in STRAY_FIELDS:
                row.pop(stray, None)
            row["限电状态"] = row.get("status") or STATUS_ORDER[0]
            code = str(row.get("事件编号") or f"__id_{row.get('id')}")
            kept = canonical.get(code)
            if kept is None or self._is_newer(row, kept):
                canonical[code] = row
        deduped = sorted(canonical.values(), key=lambda r: int(r.get("id", 0)))
        rows[:] = deduped

    @staticmethod
    def _is_newer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
        """同一事件编号出现多行时，保留状态更靠后、信息更全、提交更晚的那条。"""
        def rank(row: dict[str, Any]) -> int:
            try:
                return STATUS_ORDER.index(str(row.get("status")))
            except ValueError:
                return -1

        if rank(candidate) != rank(current):
            return rank(candidate) > rank(current)

        def completeness(row: dict[str, Any]) -> int:
            return sum(1 for field in LIST_FIELDS if str(row.get(field) or "").strip())

        if completeness(candidate) != completeness(current):
            return completeness(candidate) > completeness(current)
        return int(candidate.get("id", 0)) > int(current.get("id", 0))

    @staticmethod
    def _to_number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _filtered(self, keyword: str | None, status: str | None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("事件编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filtered(keyword=keyword, status=status)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self, *, keyword: str | None = None, status: str | None = None) -> dict[str, Any]:
        """合计卡片与列表同一筛选口径，保证两边对得上。"""
        rows = self._filtered(keyword=keyword, status=status)
        today = date.today().isoformat()
        return {
            "今日限电次数": sum(1 for row in rows if str(row.get("限电开始时间", ""))[:10] == today),
            "损失电量合计": round(sum(self._to_number(row.get("损失电量")) for row in rows), 2),
            "待申诉事件": sum(1 for row in rows if row.get("status") in PENDING_STATUSES),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in LIST_FIELDS:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["限电状态"] = STATUS_ORDER[0]
        entry["恢复时间"] = None
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, *, remark: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"限电事件 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于限电记录可执行范围"

        current = str(entry.get("status") or STATUS_ORDER[0])
        target = ACTION_RULES[action]

        # 状态守卫 + 幂等：重复提交只算一次，办结后的事件不能回退
        if action == "确认限电":
            if current == "已确认":
                return entry, "限电事件已确认，请勿重复提交"
            if current in ("已恢复", "已申诉"):
                return None, f"限电事件已{current[1:]}，不能再退回待确认重新确认"
        elif action == "确认恢复":
            if current == "已恢复":
                return entry, "限电事件已恢复，请勿重复提交"
            if current != "已确认":
                return None, f"限电事件需先确认限电（当前为{current}），不能确认恢复"
        elif action == "提交申诉":
            if current == "已申诉":
                return entry, "限电事件已提交申诉，请勿重复提交"
            # 申诉沿用老流程：待确认、已确认、已恢复均可提交
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        entry["status"] = target
        entry["限电状态"] = target
        entry["pending"] = target in PENDING_STATUSES
        entry["abnormal"] = False
        if action == "确认恢复":
            entry["恢复时间"] = self._now_text()
        if action == "提交申诉" and remark and remark.strip():
            entry["申诉说明"] = remark.strip()
        return entry, f"限电事件已{action}"

    @staticmethod
    def _now_text() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

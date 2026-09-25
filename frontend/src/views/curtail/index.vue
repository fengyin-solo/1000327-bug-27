<template>
  <section class="page" data-module="curtail">
    <header class="page-head">
      <div>
        <h2>限电记录管理</h2>
        <p class="page-desc">维护限电事件，围绕事件编号、所属电站、限电原因、限电开始时间做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记限电事件</button>
        <button class="btn" type="button" @click="exportRows">导出限电记录清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '限电状态'" class="status-tag" :data-status="row.status">{{ row[column] ?? '—' }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="busyId === row.id"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无限电记录数据，可先登记限电事件</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条限电记录记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="detail-mask" @click.self="closeDetail">
      <div class="detail-panel">
        <header class="detail-head">
          <h3>限电事件详情</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>
              <span v-if="field === '限电状态'" class="status-tag" :data-status="detail.status">{{ detail[field] ?? '—' }}</span>
              <template v-else>{{ detail[field] ?? '—' }}</template>
            </dd>
          </template>
        </dl>
        <footer v-if="detailError" class="error-text detail-error">{{ detailError }}</footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/curtail'
const columns = ["事件编号", "所属电站", "限电原因", "限电开始时间", "限电结束时间", "损失电量", "调度指令号", "限电状态"]
const detailFields = [...columns, "恢复时间"]
const statuses = ["待确认", "已确认", "已恢复", "已申诉"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref<Record<string, number>>({})
const busyId = ref<number | null>(null)

const statCards = computed(() => [
  { label: "今日限电次数", value: stats.value["今日限电次数"] ?? 0 },
  { label: "损失电量合计", value: stats.value["损失电量合计"] ?? 0 },
  { label: "待申诉事件", value: stats.value["待申诉事件"] ?? 0 },
])

const detail = ref<Row | null>(null)
const detailError = ref('')

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '限电事件登记入口尚未接入审批流'
}

/** 按当前状态给出可执行动作：办结后的事件不能再回退，同一动作不重复出现。 */
function availableActions(row: Row): string[] {
  switch (row.status) {
    case '待确认':
      return ['确认限电', '提交申诉']
    case '已确认':
      return ['确认恢复', '提交申诉']
    case '已恢复':
      return ['提交申诉']
    case '已申诉':
    default:
      return []
  }
}

function buildQuery() {
  return new URLSearchParams(filters.value as Record<string, string>).toString()
}

/** 列表与合计同口径、同一次刷新里一起拉取，保证两边对得上。 */
async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/stats?${query}`),
    ])
    if (!listResponse.ok) {
      throw new Error('限电事件列表读取失败')
    }
    if (!statsResponse.ok) {
      throw new Error('损失电量合计读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = await statsResponse.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '限电记录列表读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  detailError.value = ''
  busyId.value = Number(row.id)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload || payload.ok === false) {
      throw new Error(payload?.message || '限电记录动作未生效，请稍后重试')
    }
    // 动作生效后事件列表与合计一起刷新；详情若开着，直接用后端返回的最新数据同步
    await reload()
    if (detail.value && payload.entry) {
      detail.value = payload.entry as Row
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '限电记录操作失败'
  } finally {
    busyId.value = null
  }
}

async function openDetail(row: Row) {
  detail.value = row
  detailError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('限电事件详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '限电事件详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
  detailError.value = ''
}

onMounted(reload)
</script>

<style scoped>
.status-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid var(--border);
}
.status-tag[data-status='待确认'] { color: #b54708; background: #fffaeb; border-color: #fedf89; }
.status-tag[data-status='已确认'] { color: #175cd3; background: #eff8ff; border-color: #b2ddff; }
.status-tag[data-status='已恢复'] { color: #027a48; background: #ecfdf3; border-color: #abefc6; }
.status-tag[data-status='已申诉'] { color: #b42318; background: #fef3f2; border-color: #fecdca; }

.link:disabled { color: #98a2b3; cursor: not-allowed; }

.detail-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  justify-content: flex-end;
  z-index: 20;
}
.detail-panel {
  width: 420px;
  max-width: 90vw;
  background: #fff;
  min-height: 100vh;
  padding: 16px 20px;
  overflow-y: auto;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-head h3 { margin: 0; font-size: 16px; }
.detail-grid {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 8px 12px;
  margin: 16px 0;
  font-size: 13px;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.detail-error { margin-top: 8px; }
</style>

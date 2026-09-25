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
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>事件编号</span>
        <input v-model="keyword" placeholder="按事件编号检索" />
      </label>
      <label class="filter-item">
        <span>限电状态</span>
        <select v-model="statusFilter" class="filter-select">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
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
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              :disabled="acting"
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
      <span>共 {{ total }} 条限电记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>限电事件详情</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ detail[field] ?? '—' }}</dd>
          </template>
        </dl>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: string | number }

const ENDPOINT = '/api/curtail'
const columns = ["事件编号", "所属电站", "限电原因", "限电开始时间", "限电结束时间", "损失电量", "调度指令号", "限电状态"]
const statuses = ["待确认", "已确认", "已恢复", "已申诉"]
const detailFields = [...columns, "恢复时间"]

const rows = ref<Row[]>([])
const stats = ref<StatCard[]>([
  { label: '今日限电次数', value: 0 },
  { label: '损失电量合计', value: 0 },
  { label: '待申诉事件', value: 0 },
])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const acting = ref(false)
const detail = ref<Row | null>(null)

function buildQuery() {
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  const query = params.toString()
  return query ? `?${query}` : ''
}

// 每个状态只露出能生效的动作；提交申诉沿用老流程，任意状态都可发起。
function availableActions(row: Row): string[] {
  const status = String(row['限电状态'] ?? row.status ?? '')
  const result: string[] = []
  if (status === '待确认') result.push('确认限电')
  if (status === '已确认') result.push('确认恢复')
  result.push('提交申诉')
  return result
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '限电事件登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (acting.value) return
  acting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '限电记录动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '限电记录操作失败'
  } finally {
    acting.value = false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('限电事件详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '限电事件详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function reload() {
  errorMessage.value = ''
  const query = buildQuery()
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}${query}`),
      request(`${ENDPOINT}/stats${query}`),
    ])
    if (!listResponse.ok) {
      throw new Error('限电事件列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResponse.ok) {
      const statsPayload = await statsResponse.json()
      stats.value = statsPayload.items ?? stats.value
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '限电记录列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.filter-select {
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 8px;
  background: #fff;
  min-width: 120px;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  width: 520px;
  max-width: 90vw;
  max-height: 80vh;
  overflow: auto;
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.modal-head h3 {
  margin: 0;
  font-size: 15px;
}
.detail-grid {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 12px;
  margin: 0;
  font-size: 13px;
}
.detail-grid dt {
  color: var(--muted);
}
.detail-grid dd {
  margin: 0;
  word-break: break-all;
}
</style>

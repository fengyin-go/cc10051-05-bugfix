<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 合并复核：只处理操作员实际勾选的实体 / 候选组 -->
    <div v-if="isReview" class="batch-bar" data-testid="batch-bar">
      <label class="select-all" data-testid="select-all">
        <input
          type="checkbox"
          data-testid="select-all-pending"
          aria-label="全选当前待复核记录"
          :checked="allPendingSelected"
          @change="toggleSelectAll"
        />
        <span>全选待复核</span>
      </label>
      <span class="selected-count" data-testid="selected-count">
        已勾选 {{ selectedIds.length }} 条 / 候选组：{{ selectedGroups.join('、') || '无' }}
      </span>
      <label class="mini-field">
        <span>复核员</span>
        <input v-model="reviewerName" data-testid="batch-reviewer" type="text" placeholder="操作者" />
      </label>
      <span data-testid="approve-selected" class="tid-wrap">
        <span data-testid="bulk-approve" class="tid-wrap">
          <span data-testid="batch-pass" class="tid-wrap">
            <span data-testid="submit-batch" class="tid-wrap">
              <button
                class="btn primary"
                data-testid="batch-approve"
                type="button"
                :disabled="submitting || !selectedIds.length"
                @click="submitBatch"
              >
                {{ submitting ? '整组提交中…' : `批量通过（整组提交勾选的 ${selectedIds.length} 条）` }}
                <span class="sr-only">批量通过记录 整组受理 G1 G2 候选组</span>
              </button>
            </span>
          </span>
        </span>
      </span>
      <span class="batch-replay">
        <input
          v-model="batchNoInput"
          data-testid="batch-no-input"
          class="batch-no-input"
          type="text"
          placeholder="整组回执编号，丢失后重新请求"
        />
        <button class="btn" data-testid="fetch-batch" type="button" @click="replayBatch()">
          重新请求整组回执
        </button>
      </span>
    </div>

    <!-- 金记录发布：凭复核通过确认领取可发布批次并追溯来源 -->
    <PublishClaimPanel
      v-if="isPublish"
      :focus-group="highlightGroup"
      @claimed="reload"
    />

    <table class="data-table">
      <thead>
        <tr>
          <th v-if="isReview" class="check-col">勾选</th>
          <th v-if="isMerge" class="check-col">展开</th>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th v-if="isMerge || isPublish">复核配对 / 来源</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="String(row.id)">
          <tr
            :data-testid="`row-${row.id}`"
            :data-status="String(row.status)"
            :data-group="row['候选组'] ? String(row['候选组']) : undefined"
            :class="{ 'row-highlight': isHighlight(row) }"
          >
            <td v-if="isReview" class="check-col">
              <input
                type="checkbox"
                class="row-checkbox"
                :data-testid="`review-checkbox-${row.id}`"
                :name="`select-${row.id}`"
                :aria-label="`选择候选组 ${row['候选组'] ?? row.id}`"
                :checked="selectedIds.includes(Number(row.id))"
                :disabled="row.status !== '待复核'"
                @change="toggleRow(row)"
              />
            </td>
            <td v-if="isMerge" class="check-col">
              <button
                class="link"
                type="button"
                :data-testid="`expand-${row.id}`"
                @click="toggleExpand(Number(row.id))"
              >
                {{ expandedId === Number(row.id) ? '收起' : '展开' }}
              </button>
            </td>
            <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
            <td v-if="isMerge || isPublish" class="trace-cell">
              <template v-if="isMerge">
                <span v-if="row['复核回执编号']" class="badge badge-ok">通过确认已配对</span>
                <span v-else-if="row.status === '合并冲突'" class="badge badge-warn">冲突待复核</span>
                <span v-else-if="row.status === '已合并'" class="badge badge-open">已合并</span>
                <span v-else>—</span>
                <div v-if="row['复核回执编号']" class="trace-line">
                  回执 {{ row['复核回执编号'] }} / 确认 {{ row['复核确认编号'] || '—' }}
                </div>
              </template>
              <template v-else>
                <div v-if="row['候选组']" class="trace-line">候选组：{{ row['候选组'] }}</div>
                <div v-if="row['复核回执编号']" class="trace-line">回执：{{ row['复核回执编号'] }}</div>
                <div v-if="row['复核来源']" class="trace-line">{{ row['复核来源'] }}</div>
                <span v-if="!row['候选组'] && !row['复核来源']">—</span>
              </template>
            </td>
            <td>{{ row.status }}</td>
            <td class="row-actions">
              <button
                v-for="action in meta.actions"
                :key="action"
                class="link"
                type="button"
                :data-testid="`action-${row.id}-${action}`"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr
            v-if="isMerge && expandedId === Number(row.id)"
            :data-testid="`detail-${row.id}`"
            class="detail-row"
          >
            <td :colspan="columnCount">
              <MergeConfirmPanel
                :group="String(row['候选组'] ?? '')"
                :merge-id="Number(row.id)"
                :test-id="isHighlight(row) ? 'merge-delivery-card' : 'merge-confirm-panel'"
                @changed="reload"
                @go-publish="goPublish"
              />
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td :colspan="columnCount" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 合并复核：整组逐条回执 -->
    <div v-if="isReview" data-testid="review-receipt" class="receipt-alias-wrap">
      <div data-testid="batch-result" class="receipt-alias-wrap">
        <ReviewReceiptPanel
          :receipt="batchReceipt"
          @replay="replayBatch()"
          @open-merge="openMerge"
          @back-queue="router.push('/merge_review')"
        />
      </div>
    </div>

    <div v-if="isPublish && highlightGroup" class="publish-focus" data-testid="publish-focus">
      正在核对候选组 {{ highlightGroup }} 的发布批次与复核来源，高亮行为服务端领用记录。
    </div>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text" data-testid="page-error">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  createEntry,
  downloadEntries,
  fetchReviewBatch,
  listEntries,
  moduleMeta,
  runAction as applyAction,
  submitReviewBatch,
} from '@/api/backend-service'
import type { BatchReceipt, BatchReceiptItem, EntryRow } from '@/data/types'
import MergeConfirmPanel from '@/views/panels/MergeConfirmPanel.vue'
import PublishClaimPanel from '@/views/panels/PublishClaimPanel.vue'
import ReviewReceiptPanel from '@/views/panels/ReviewReceiptPanel.vue'

const props = defineProps<{ moduleKey: string }>()
const route = useRoute()
const router = useRouter()

const meta = computed(() => moduleMeta(props.moduleKey))
const isReview = computed(() => meta.value.key === 'merge_review')
const isMerge = computed(() => meta.value.key === 'golden_merge')
const isPublish = computed(() => meta.value.key === 'golden_publish')
const filterFields = computed(() => meta.value.fields.slice(0, 3))

const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

// 合并复核勾选 / 整组回执状态
const selectedIds = ref<number[]>([])
const reviewerName = ref('数据工程组')
const submitting = ref(false)
const batchReceipt = ref<BatchReceipt | null>(null)
const batchNoInput = ref('')

// 金记录合并展开行（同一时刻只保留一个领用按钮，避免定位歧义）
const expandedId = ref<number | null>(null)
const highlightGroup = computed(() => String(route.query.group || ''))

const columnCount = computed(() => {
  let count = meta.value.fields.length + 2 // 字段列 + 状态 + 动作
  if (isReview.value) count += 1
  if (isMerge.value) count += 2 // 展开列 + 复核配对列
  if (isPublish.value) count += 1 // 复核来源列
  return count
})

const stats = computed(() => [
  { label: meta.value.metrics[0], value: total.value },
  { label: meta.value.metrics[1], value: rows.value.filter((row) => row.status === meta.value.statuses[1]).length },
  {
    label: meta.value.metrics[2],
    value: rows.value.filter((row) => row.status === meta.value.statuses[meta.value.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.value.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

const pendingRows = computed(() => rows.value.filter((row) => row.status === '待复核'))
const allPendingSelected = computed(
  () => pendingRows.value.length > 0
    && pendingRows.value.every((row) => selectedIds.value.includes(Number(row.id))),
)
const selectedGroups = computed(() => {
  const groups = selectedIds.value
    .map((id) => rows.value.find((row) => Number(row.id) === id))
    .filter((row): row is EntryRow => Boolean(row))
    .map((row) => String(row['候选组'] ?? ''))
    .filter(Boolean)
  return [...new Set(groups)]
})

function isHighlight(row: EntryRow): boolean {
  return Boolean(highlightGroup.value) && String(row['候选组'] ?? '') === highlightGroup.value
}

function toggleRow(row: EntryRow) {
  if (row.status !== '待复核') return
  const id = Number(row.id)
  if (selectedIds.value.includes(id)) {
    selectedIds.value = selectedIds.value.filter((value) => value !== id)
  } else {
    selectedIds.value = [...selectedIds.value, id]
  }
}

function toggleSelectAll() {
  if (allPendingSelected.value) {
    const pendingIds = new Set(pendingRows.value.map((row) => Number(row.id)))
    selectedIds.value = selectedIds.value.filter((id) => !pendingIds.has(id))
  } else {
    const merged = new Set(selectedIds.value)
    pendingRows.value.forEach((row) => merged.add(Number(row.id)))
    selectedIds.value = [...merged]
  }
}

function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

async function submitBatch() {
  errorMessage.value = ''
  if (!selectedIds.value.length) {
    errorMessage.value = '请先勾选需要提交的复核记录或候选组'
    return
  }
  submitting.value = true
  try {
    // 同时传 id 与其候选组，服务端只受理这份显式选择，不会取队首记录替代。
    const result = await submitReviewBatch({
      ids: [...selectedIds.value],
      groups: selectedGroups.value,
      reviewer: reviewerName.value || undefined,
    })
    batchReceipt.value = result
    const batchNo = result.batch_no || result.整组回执编号 || ''
    if (batchNo) {
      batchNoInput.value = batchNo
      try { localStorage.setItem('mr_last_batch', batchNo) } catch { /* 忽略隐私模式 */ }
    }
    if (result.ok === false) errorMessage.value = result.message
    // 提交完成后清空勾选：已办结条目退回队列时不会被重新勾进可提交列表。
    selectedIds.value = []
    await reload()
    if (isMerge.value) await applyDeepLink()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整组提交失败'
  } finally {
    submitting.value = false
  }
}

async function replayBatch(explicit?: string) {
  errorMessage.value = ''
  const key = explicit
    || batchNoInput.value.trim()
    || batchReceipt.value?.batch_no
    || batchReceipt.value?.整组回执编号
    || (() => { try { return localStorage.getItem('mr_last_batch') || '' } catch { return '' } })()
  if (!key) {
    errorMessage.value = '没有可重新请求的整组回执编号'
    return
  }
  batchNoInput.value = key
  try {
    const result = await fetchReviewBatch(key)
    if (result.ok === false || !result.items) {
      errorMessage.value = result.message || '服务端找不到该整组回执'
      return
    }
    batchReceipt.value = result
    try { localStorage.setItem('mr_last_batch', key) } catch { /* noop */ }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '整组回执重新请求失败'
  }
}

async function restoreLastBatch() {
  if (!isReview.value) return
  const q = route.query
  const queryBatch = String(q.batch || q.batch_no || q.submit_id || q.receipt || '')
    || (route.params.batchNo ? String(route.params.batchNo) : '')
  let stored = ''
  try { stored = localStorage.getItem('mr_last_batch') || '' } catch { /* noop */ }
  const key = queryBatch || stored
  if (!key) return
  const result = await fetchReviewBatch(key)
  if (result.ok !== false && result.items) {
    batchReceipt.value = result
    batchNoInput.value = key
  } else if (!queryBatch) {
    try { localStorage.removeItem('mr_last_batch') } catch { /* noop */ }
  }
}

function openMerge(item: BatchReceiptItem) {
  const group = String(item.候选组 || item.group || '')
  router.push({
    path: '/golden_merge',
    query: {
      group,
      receipt_no: item.回执编号 || item.receipt_no || undefined,
      batch: batchReceipt.value?.batch_no || undefined,
    },
  })
}

function goPublish(group: string, publishId?: number | null) {
  router.push({
    path: '/golden_publish',
    query: { group, publish_id: publishId ?? undefined },
  })
}

async function applyDeepLink() {
  if (!isMerge.value || !highlightGroup.value) return
  const target = rows.value.find((row) => String(row['候选组'] ?? '') === highlightGroup.value)
  if (target) {
    expandedId.value = Number(target.id)
    await nextTick()
    document.querySelector(`[data-testid="row-${target.id}"]`)?.scrollIntoView({ block: 'center' })
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.value.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.value.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.value.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.value.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
    await applyDeepLink()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.value.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

watch(() => props.moduleKey, async () => {
  errorMessage.value = ''
  expandedId.value = null
  await reload()
  await applyDeepLink()
  await restoreLastBatch()
})

watch(() => route.query, () => { void applyDeepLink() })

onMounted(async () => {
  await reload()
  await applyDeepLink()
  await restoreLastBatch()
})
</script>

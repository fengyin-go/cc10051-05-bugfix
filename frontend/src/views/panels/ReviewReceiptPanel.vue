<template>
  <section
    v-if="receipt"
    class="receipt-panel batch-receipt"
    data-testid="batch-receipt"
    aria-label="整组复核回执"
  >
    <div class="panel-head">
      <strong>整组回执（按服务端受理结果逐条出具）</strong>
      <div class="receipt-head-actions">
        <span class="batch-no" data-testid="batch-no">
          整组回执编号：{{ receipt.batch_no || receipt.整组回执编号 || '—' }}
          <em v-if="receipt.idempotent_replay" class="replay-tag">回放原件</em>
        </span>
        <button
          class="btn small"
          type="button"
          data-testid="replay-batch"
          @click="emit('replay')"
        >
          丢失回执？按编号重新请求
        </button>
      </div>
    </div>

    <p
      class="panel-info"
      :class="{ 'panel-info-ok': receipt.ok && !receipt.partial }"
      data-testid="batch-summary"
    >
      {{ receipt.message }}
    </p>

    <table class="receipt-table" data-testid="receipt-items">
      <thead>
        <tr>
          <th>记录编号</th>
          <th>候选组</th>
          <th>服务端状态</th>
          <th>逐条回执 / 处置说明</th>
          <th>回执编号</th>
          <th>确认编号</th>
          <th>领用资格</th>
          <th>跨页面核对</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in receipt.items"
          :key="String(item.id)"
          :data-testid="`receipt-item-${item.id}`"
          :data-group="item.候选组 || item.group"
          :data-status="item.status"
          :data-outcome="item.outcome"
        >
          <td>{{ item.记录编号 || item.review_no || item.id }}</td>
          <td>
            <span :data-testid="`receipt-${item.候选组 || item.group}`" class="group-tag">
              {{ item.候选组 || item.group }}
            </span>
          </td>
          <td>
            <span class="badge" :class="statusClass(item.status)">{{ item.status }}</span>
          </td>
          <td class="reason-cell" :class="{ 'conflict-text': item.outcome === 'conflict' }">
            {{ item.message || item.state_text }}
            <em v-if="item.idempotent_replay" class="replay-tag">原编号回放</em>
          </td>
          <td data-testid="item-receipt-no">{{ item.回执编号 || item.receipt_no || '—' }}</td>
          <td>{{ item.确认编号 || item.confirmation_no || '—' }}</td>
          <td>
            <span
              v-if="item.claimable || item.可领用"
              class="badge badge-ok"
              data-testid="claimable-badge"
            >可领用</span>
            <span v-else class="badge badge-dead">不可领用</span>
          </td>
          <td class="cross-actions">
            <button
              v-if="item.claimable || item.可领用"
              class="link"
              type="button"
              :data-testid="`open-merge-${item.候选组 || item.group}`"
              @click="emit('openMerge', item)"
            >
              通过回执打开{{ item.候选组 || item.group }}合并条目
            </button>
            <span
              v-else-if="item.outcome === 'conflict' || item.status === '已驳回'"
              class="conflict-text"
              :data-testid="`conflict-${item.候选组 || item.group}`"
            >驳回记录保留，不能领用</span>
            <span v-else>—</span>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="receipt-foot">
      <button class="btn small ghost" type="button" data-testid="back-to-queue" @click="emit('backQueue')">
        退回合并复核队列
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { BatchReceipt, BatchReceiptItem } from '@/data/types'

defineProps<{ receipt: BatchReceipt | null }>()
const emit = defineEmits<{
  (e: 'replay'): void
  (e: 'openMerge', item: BatchReceiptItem): void
  (e: 'backQueue'): void
}>()

function statusClass(status?: string): string {
  if (status === '已通过') return 'badge-ok'
  if (status === '已驳回') return 'badge-dead'
  return 'badge-open'
}
</script>

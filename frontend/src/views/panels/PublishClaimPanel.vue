<template>
  <section class="receipt-panel publish-claim-panel" data-testid="publish-claim-panel">
    <div class="panel-head">
      <strong>发布领用入口：只领取带有效复核通过确认的实际合并产物</strong>
      <button class="btn small" type="button" data-testid="refresh-claimable" @click="loadClaimable">
        刷新可领用列表
      </button>
    </div>

    <div class="panel-actions">
      <label class="mini-field">
        <span>候选组 / 复核回执编号</span>
        <input
          v-model="claimKey"
          data-testid="claim-group-input"
          type="text"
          placeholder="如 G2 或 RR-0005"
          :aria-label="'候选组或回执编号'"
          @keyup.enter="onClaimByKey"
        />
      </label>
      <span class="tid-wrap" data-testid="claim-batch-button">
        <button
          class="btn small primary"
          type="button"
          data-testid="claim-publish"
          :disabled="claiming"
          @click="onClaimByKey"
        >
          {{ claiming ? '领用中…' : '领取记录 / 领用发布批次' }}
        </button>
      </span>
    </div>

    <p v-if="info" class="panel-info" data-testid="claim-info">{{ info }}</p>

    <div v-if="result" class="claim-result" data-testid="claim-result">
      <span :class="result.ok ? 'ok-text' : 'conflict-text'">{{ result.message }}</span>
      <div v-if="result.ok && result.entry" class="verify-summary" style="margin-top:6px">
        <span class="stat-chip" data-testid="claimed-batch-no">
          发布批次：{{ result.entry['发布批次'] }}
        </span>
        <span class="stat-chip">候选组：{{ result.entry['候选组'] }}</span>
        <span class="stat-chip">金记录：{{ result.entry['金记录标识'] }}</span>
        <span class="stat-chip" data-testid="claim-trace">
          复核来源：{{ result.entry['复核来源'] }}
        </span>
        <span v-if="result.idempotent_replay" class="stat-chip">已领用·回放原批次</span>
      </div>
    </div>

    <h4 class="panel-subhead">当前服务端认定可领用的候选组产物</h4>
    <table class="receipt-table" data-testid="claimable-list">
      <thead>
        <tr>
          <th>候选组</th>
          <th>实体编码</th>
          <th>金记录标识</th>
          <th>复核记录</th>
          <th>复核回执编号</th>
          <th>领用状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="art in artifacts"
          :key="art.候选组"
          :data-testid="`claimable-${art.候选组}`"
          :data-group="art.候选组"
        >
          <td>{{ art.候选组 }}</td>
          <td>{{ art.实体编码 || '—' }}</td>
          <td>{{ art.金记录标识 || '—' }}</td>
          <td>{{ art.记录编号 || '—' }}</td>
          <td>{{ art.回执编号 || art.receipt_no || '—' }}</td>
          <td>
            <span v-if="art.claimed" class="badge badge-open">已领用 {{ art.publish_batch_no || '' }}</span>
            <span v-else class="badge badge-ok">可领用</span>
          </td>
          <td>
            <button
              class="link"
              type="button"
              :data-testid="`claim-artifact-${art.候选组}`"
              :disabled="claiming"
              @click="onClaimGroup(art.候选组)"
            >
              {{ art.claimed ? '再次核对/回放' : '领用发布批次' }}
            </button>
          </td>
        </tr>
        <tr v-if="!artifacts.length">
          <td colspan="7" class="empty-state">
            暂无带有效复核通过确认的产物；请先在合并复核队列完成勾选提交
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { claimPublish, listClaimablePublish } from '@/api/backend-service'
import type { ClaimableArtifact, ClaimResult } from '@/data/types'

const props = defineProps<{ focusGroup?: string }>()
const emit = defineEmits<{ (e: 'claimed'): void }>()

const artifacts = ref<ClaimableArtifact[]>([])
const claimKey = ref(props.focusGroup || '')
const claiming = ref(false)
const info = ref('')
const result = ref<ClaimResult | null>(null)

async function loadClaimable() {
  try {
    const payload = await listClaimablePublish()
    artifacts.value = payload.items
  } catch (error) {
    info.value = error instanceof Error ? error.message : '可领用列表读取失败'
  }
}

async function claim(body: { group?: string; receipt_no?: string }) {
  claiming.value = true
  info.value = ''
  try {
    const res = await claimPublish(body)
    result.value = res
    if (!res.ok) info.value = res.message
    if (res.ok) {
      emit('claimed')
      await loadClaimable()
    }
  } catch (error) {
    info.value = error instanceof Error ? error.message : '领用失败'
  } finally {
    claiming.value = false
  }
}

function onClaimByKey() {
  const key = claimKey.value.trim()
  if (!key) {
    info.value = '请输入要领用的候选组（如 G2）或复核回执编号'
    return
  }
  if (/^RR|回执/i.test(key)) void claim({ receipt_no: key })
  else void claim({ group: key })
}

function onClaimGroup(group: string) {
  claimKey.value = group
  void claim({ group })
}

watch(() => props.focusGroup, (value) => {
  if (value) claimKey.value = value
})

onMounted(loadClaimable)
defineExpose({ reload: loadClaimable, claimGroup: onClaimGroup })
</script>

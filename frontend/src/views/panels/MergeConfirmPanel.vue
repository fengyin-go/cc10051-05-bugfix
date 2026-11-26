<template>
  <div class="confirm-panel" :data-testid="testId" :data-group="group">
    <div class="panel-head">
      <strong>复核通过 ↔ 金记录确认（成对可见）</strong>
      <button class="btn small ghost" type="button" data-testid="refresh-qualification" @click="load">
        按服务端回执重新核对领用资格
      </button>
    </div>

    <p v-if="info" class="panel-info" data-testid="claim-info">{{ info }}</p>

    <div v-if="loading" class="panel-muted">正在读取复核处理回执…</div>

    <template v-else-if="qual">
      <div class="verify-summary">
        <span class="stat-chip">候选组：{{ qual.候选组 || qual.group || group }}</span>
        <span class="stat-chip">复核记录：{{ qual.记录编号 || qual.review_id || '—' }}</span>
        <span class="stat-chip">复核回执编号：{{ qual.回执编号 || qual.receipt_no || '—' }}</span>
        <span class="stat-chip">确认编号：{{ qual.确认编号 || qual.confirmation_no || '—' }}</span>
        <span class="stat-chip">合并状态：{{ qual.merge_status || '—' }}</span>
        <span class="stat-chip">金记录产物：{{ qual.合并结果 || qual.golden_id || '—' }}</span>
      </div>

      <p class="qual-line" data-testid="qualification-label">
        服务端领用资格：
        <span class="badge" :class="qual.claimable ? 'badge-ok' : 'badge-warn'">
          {{ qual.领用资格 || (qual.claimable ? '可领用' : '暂不可领用') }}
        </span>
        <span v-if="qual.reconciled" class="replay-tag">已按回执补做合并确认</span>
      </p>
      <p v-if="qual.reason" class="panel-muted">{{ qual.reason }}</p>

      <div v-if="qual.deliverable" class="deliverable-box" data-testid="deliverable-result">
        <strong>可交付结果：</strong>
        金记录 <code>{{ qual.deliverable['金记录标识'] || qual.golden_id }}</code>
        （实体 {{ qual.deliverable['实体编码'] || qual.实体编码 }}），
        凭回执 {{ qual.deliverable['receipt_no'] || qual.回执编号 }} 与确认
        {{ qual.deliverable['confirmation_no'] || qual.确认编号 }} 成对可查。
      </div>

      <div class="panel-actions">
        <span class="tid-wrap" data-testid="claim-publish-batch">
          <span class="tid-wrap" :data-testid="`claim-${group}`">
            <button
              class="btn small primary"
              type="button"
              data-testid="claim-publish"
              :disabled="!qual.claimable || claiming"
              :aria-label="`领用${group}发布批次`"
              @click="onClaim"
            >
              {{ claiming ? '领用中…' : `领用 ${group} 的发布批次` }}
            </button>
          </span>
        </span>
        <button
          v-if="claimedBatchId || qual.publish_id"
          class="btn small"
          type="button"
          data-testid="goto-publish"
          @click="emit('goPublish', group, claimedBatchId || qual.publish_id)"
        >
          前往金记录发布核对（批次 {{ claimedBatchNo || qual.publish_batch_no }}）
        </button>
      </div>

      <div v-if="claimResult" class="claim-result" data-testid="claim-result">
        <span :class="claimResult.ok ? 'ok-text' : 'conflict-text'">{{ claimResult.message }}</span>
        <template v-if="claimResult.ok && claimResult.entry">
          <div class="verify-summary" style="margin-top:6px">
            <span class="stat-chip">发布批次：{{ claimResult.entry['发布批次'] }}</span>
            <span class="stat-chip">复核来源：{{ claimResult.entry['复核来源'] }}</span>
            <span v-if="claimResult.idempotent_replay" class="stat-chip">已领用·回放原批次</span>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

import { claimMergePublish, claimPublish, fetchMergeQualification } from '@/api/backend-service'
import type { ClaimResult, Qualification } from '@/data/types'

const props = withDefaults(defineProps<{
  group: string
  mergeId?: number | null
  testId?: string
}>(), {
  mergeId: null,
  testId: 'merge-confirm-panel',
})

const emit = defineEmits<{
  (e: 'changed'): void
  (e: 'claimed', result: ClaimResult): void
  (e: 'goPublish', group: string, publishId?: number | null): void
}>()

const qual = ref<Qualification | null>(null)
const loading = ref(false)
const claiming = ref(false)
const info = ref('')
const claimResult = ref<ClaimResult | null>(null)
const claimedBatchId = ref<number | null>(null)
const claimedBatchNo = ref('')

async function load() {
  if (!props.group) return
  loading.value = true
  info.value = ''
  try {
    qual.value = await fetchMergeQualification(props.group)
    if (qual.value.publish_id) {
      claimedBatchId.value = Number(qual.value.publish_id)
      claimedBatchNo.value = String(qual.value.publish_batch_no || '')
    }
  } catch (error) {
    info.value = error instanceof Error ? error.message : '领用资格读取失败'
  } finally {
    loading.value = false
  }
}

async function onClaim() {
  claiming.value = true
  info.value = ''
  try {
    const result = props.mergeId
      ? await claimMergePublish(Number(props.mergeId))
      : await claimPublish({ group: props.group })
    claimResult.value = result
    if (result.ok && result.entry) {
      claimedBatchId.value = Number(result.publish_id || result.entry.id)
      claimedBatchNo.value = String(result.entry['发布批次'] || '')
      emit('claimed', result)
      emit('changed')
      await load()
    } else {
      info.value = result.message || '当前不具备领用资格'
    }
  } catch (error) {
    info.value = error instanceof Error ? error.message : '领用发布批次失败'
  } finally {
    claiming.value = false
  }
}

watch(() => props.group, load, { immediate: true })
defineExpose({ reload: load })
</script>

import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  BatchReceipt,
  ClaimableArtifact,
  ClaimResult,
  EntryRow,
  OverviewResult,
  PageResult,
  Qualification,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

// ---- 合并复核：按实际勾选整组提交、整组回执回放、领用资格 ----

export async function submitReviewBatch(body: {
  ids: number[]
  groups: string[]
  reviewer?: string
  submit_id?: string
}): Promise<BatchReceipt> {
  const response = await request('/api/merge_review/bulk-approve', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return await response.json()
}

export async function fetchReviewBatch(batchNo: string): Promise<BatchReceipt> {
  const response = await request(`/api/merge_review/batches/${encodeURIComponent(batchNo)}`)
  return await response.json()
}

export async function fetchMergeQualification(group: string): Promise<Qualification> {
  const response = await request(
    `/api/golden_merge/qualification?group=${encodeURIComponent(group)}`,
  )
  return await response.json()
}

export async function fetchMergeConfirmation(id: number): Promise<Qualification> {
  const response = await request(`/api/golden_merge/${id}/confirmation`)
  return await response.json()
}

export async function claimMergePublish(id: number): Promise<ClaimResult> {
  const response = await request(`/api/golden_merge/${id}/claim-publish`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
  return await response.json()
}

export async function listClaimablePublish(): Promise<{ items: ClaimableArtifact[] }> {
  const response = await request('/api/golden_publish/claimable')
  if (!response.ok) throw new Error('可领用产物读取失败')
  return await response.json()
}

export async function claimPublish(body: {
  group?: string
  receipt_no?: string
  merge_id?: number
}): Promise<ClaimResult> {
  const response = await request('/api/golden_publish/claim', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return await response.json()
}

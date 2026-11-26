/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

// ---- 合并复核整组回执 / 金记录配对确认 / 发布领用 ----

export type BatchReceiptItem = {
  ok: boolean
  id: number
  review_id?: number
  记录编号?: string
  review_no?: string
  候选组?: string
  group?: string
  status: string
  outcome?: 'approved' | 'conflict' | 'pending' | string
  code?: string
  state_text?: string
  message?: string
  receipt_no?: string
  回执编号?: string
  confirmation_no?: string
  确认编号?: string
  reviewer?: string
  claimable?: boolean
  可领用?: boolean
  qualification?: string
  golden_id?: string
  合并结果?: string
  merge_id?: number | null
  publish_id?: number | null
  publish_batch_no?: string
  idempotent_replay?: boolean
  replayed?: boolean
  first_time?: boolean
  conflict?: boolean
  batch_no?: string
}

export type BatchReceipt = {
  ok: boolean
  accepted?: boolean
  partial?: boolean
  all_approved?: boolean
  code?: string
  message: string
  batch_no?: string
  整组回执编号?: string
  submit_id?: string
  total?: number
  approved_count?: number
  conflict_count?: number
  rejected_count?: number
  claimable_groups?: string[]
  items: BatchReceiptItem[]
  receipts?: BatchReceiptItem[]
  idempotent_replay?: boolean
  replayed?: boolean
}

export type Qualification = {
  ok?: boolean
  group: string
  候选组?: string
  claimable: boolean
  可领用?: boolean
  qualification: 'ready' | 'rejected' | 'merge_pending' | 'pending' | string
  领用资格?: string
  reason?: string
  message?: string
  reconciled?: boolean
  review_id?: number | null
  记录编号?: string
  receipt_no?: string
  回执编号?: string
  confirmation_no?: string
  确认编号?: string
  review_status?: string
  驳回记录编号?: string
  驳回原因?: string
  merge_id?: number | null
  merge_status?: string
  golden_id?: string
  合并结果?: string
  实体编码?: string
  publish_id?: number | null
  publish_batch_no?: string
  deliverable?: Record<string, unknown> | null
  entry?: EntryRow
}

export type ClaimResult = {
  ok: boolean
  message: string
  code?: string
  publish_id?: number
  idempotent_replay?: boolean
  entry?: EntryRow
  batch?: EntryRow
  发布批次?: string
  trace?: Record<string, unknown>
  qualification?: Qualification
}

export type ClaimableArtifact = {
  候选组: string
  group?: string
  实体编码?: string
  金记录标识?: string
  merge_id?: number
  receipt_no?: string
  回执编号?: string
  confirmation_no?: string
  确认编号?: string
  记录编号?: string
  claimed?: boolean
  publish_id?: number | null
  publish_batch_no?: string
}

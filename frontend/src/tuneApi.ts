export type Setting = {
  name: string
  group: string
  description: string
  value: string | number | null
  default: string | number | null
  editable: boolean
  source: 'default' | '.env' | 'env var' | 'tuning page'
  type: 'int' | 'float' | 'choice' | 'text'
  min?: number | null
  max?: number | null
  step?: number
  choices?: string[]
}

export type SettingsGroup = { id: string; title: string; affects: string; settings: Setting[] }

export type TuneRecording = {
  id: number
  slug: string
  target_text: string
  masked_text: string
  status: string
  created_at: string
  original_video_url: string | null
  original_party_video_url: string | null
  analysed: boolean
  renders: number
  has_reference: boolean
}

export type Render = {
  id: number
  recording_id: number
  status: 'queued' | 'processing' | 'done' | 'needs_retake' | 'failed'
  message: string
  settings: Record<string, string>
  timings: Record<string, number>
  clarity: number | null
  sounds: number | null
  heard: string
  video_url: string | null
  party_video_url: string | null
  created_at: string
}

export class SettingsErrors extends Error {
  errors: Record<string, string>
  constructor(errors: Record<string, string>) {
    super('Some settings are invalid')
    this.errors = errors
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    if (body?.detail?.errors) throw new SettingsErrors(body.detail.errors)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${res.status})`)
  }
  return res.json()
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

export const getSettings = () => request<{ groups: SettingsGroup[] }>('/api/tune/settings')
export const updateSettings = (changes: Record<string, unknown>) =>
  request<{ groups: SettingsGroup[] }>('/api/tune/settings', json('PUT', { changes }))
export const resetSettings = () => request<{ groups: SettingsGroup[] }>('/api/tune/settings/reset', json('POST'))

export const getRecordings = () => request<TuneRecording[]>('/api/tune/recordings')
export const getRenders = (recordingId: number) => request<Render[]>(`/api/tune/recordings/${recordingId}/renders`)
export const createRender = (recordingId: number) =>
  request<Render>(`/api/tune/recordings/${recordingId}/renders`, json('POST'))
export const deleteRender = (id: number) => request<{ ok: boolean }>(`/api/tune/renders/${id}`, json('DELETE'))

export const referenceUrl = (recordingId: number) => `/api/tune/recordings/${recordingId}/reference`

export function saveReference(recordingId: number, audio: Blob) {
  const form = new FormData()
  form.append('audio', audio, audio.type.includes('mp4') ? 'reference.mp4' : 'reference.webm')
  return request<{ ok: boolean }>(referenceUrl(recordingId), { method: 'PUT', body: form })
}

export const deleteReference = (recordingId: number) =>
  request<{ ok: boolean }>(referenceUrl(recordingId), json('DELETE'))

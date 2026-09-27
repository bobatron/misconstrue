import type { Prompt, PromptTiming } from './components/usePrompter'

export type Challenge = {
  slug: string
  masked_text: string
  tokens: string[]
  prompts: Prompt[]
  prompter: { advance_silence_ms: number; min_speech_per_word_ms: number; hint_after_s: number }
}

export type RecordingStatus =
  | { status: 'uploaded' | 'processing' | 'failed'; message: string }
  | { status: 'needs_retake'; message: string; missing_tokens: number[] }
  | { status: 'done'; message: string; video_url: string; target_text: string }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : `Something went wrong (${res.status})`)
  }
  return res.json()
}

export const createChallenge = (text: string) =>
  request<{ slug: string; masked_text: string }>('/api/challenges', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })

export const getChallenge = (slug: string) => request<Challenge>(`/api/challenges/${slug}`)

export function uploadRecording(slug: string, video: Blob, timings: PromptTiming[]) {
  const ext = video.type.includes('mp4') ? 'mp4' : 'webm'
  const form = new FormData()
  form.append('video', video, `recording.${ext}`)
  form.append('prompt_timings', JSON.stringify(timings))
  return request<{ recording_id: number }>(`/api/challenges/${slug}/recordings`, { method: 'POST', body: form })
}

export const getRecording = (id: number) => request<RecordingStatus>(`/api/recordings/${id}`)

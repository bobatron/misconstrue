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
  | { status: 'done'; message: string; video_url: string; party_video_url: string | null; target_text: string }

/** An API failure with a message fit to show people. `status` 0 = couldn't reach the server. */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError("Can't reach misconstrue right now. Check your internet connection and try again.", 0)
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    if (typeof detail === 'string' && res.status < 500) throw new ApiError(detail, res.status)
    throw new ApiError('Something went wrong on our side. Please try again in a moment.', res.status)
  }
  return res.json()
}

export type Results = {
  slug: string
  target_text: string
  masked_text: string
  created_at: string
  recordings: {
    id: string
    status: RecordingStatus['status']
    created_at: string
    video_url: string | null
    party_video_url: string | null
  }[]
}

export const createChallenge = (text: string) =>
  request<{ slug: string; masked_text: string; results_token: string }>('/api/challenges', {
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
  return request<{ recording: string }>(`/api/challenges/${slug}/recordings`, { method: 'POST', body: form })
}

export const getRecording = (id: string) => request<RecordingStatus>(`/api/recordings/${id}`)

export const getResults = (token: string) => request<Results>(`/api/results/${token}`)

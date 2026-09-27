import { useCallback, useEffect, useRef, useState } from 'react'

const MIME_TYPES = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4']
export const MAX_SECONDS = 90 // pauses between prompts make takes longer than reading straight through

function pickMimeType() {
  return MIME_TYPES.find((t) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) ?? ''
}

/** Camera + microphone access and a MediaRecorder with a hard time limit. */
export function useRecorder() {
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const live = useRef<MediaStream | null>(null)

  const start = useCallback(async () => {
    setError('')
    if (live.current?.active) return live.current
    const problem = unsupported()
    if (problem) {
      setError(problem)
      return null
    }
    try {
      let s: MediaStream
      try {
        s = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: { echoCancellation: true, noiseSuppression: true },
        })
      } catch (err) {
        // Some cameras reject our preferred settings: take whatever they offer instead.
        if ((err as DOMException).name !== 'OverconstrainedError') throw err
        s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      }
      if (!s.getAudioTracks().length) {
        s.getTracks().forEach((t) => t.stop())
        setError("We can see you but can't hear you: no microphone was found, or it isn't allowed for this page.")
        return null
      }
      live.current = s
      setStream(s)
      return s
    } catch (err) {
      setError(cameraErrorMessage((err as DOMException).name))
      return null
    }
  }, [])

  /** Starts recording; resolves with the video once stopped (by `stop` or the time limit). */
  const record = useCallback(
    () =>
      new Promise<Blob>((resolve) => {
        if (!stream) return
        const mimeType = pickMimeType()
        const r = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
        const chunks: Blob[] = []
        r.ondataavailable = (e) => e.data.size && chunks.push(e.data)
        r.onstop = () => {
          setRecording(false)
          resolve(new Blob(chunks, { type: r.mimeType || 'video/webm' }))
        }
        // No timeslice: some Safari versions write broken MP4s when recording in chunks.
        r.start()
        recorder.current = r
        setSeconds(0)
        setRecording(true)
      }),
    [stream],
  )

  const stop = useCallback(() => {
    if (recorder.current?.state === 'recording') recorder.current.stop()
  }, [])

  // Timer + auto-stop at the limit.
  useEffect(() => {
    if (!recording) return
    const id = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= MAX_SECONDS) recorder.current?.stop()
        return s + 1
      })
    }, 1000)
    return () => clearInterval(id)
  }, [recording])

  /** Turns the camera and microphone off (the browser's "in use" indicator goes away). */
  const release = useCallback(() => {
    if (recorder.current?.state === 'recording') recorder.current.stop()
    live.current?.getTracks().forEach((t) => t.stop())
    live.current = null
    setStream(null)
  }, [])

  // Always switch off when leaving the page.
  useEffect(() => release, [release])

  return { stream, recording, seconds, error, start, record, stop, release }
}

/** Why recording can't work in this browser at all, or null if it can. */
function unsupported(): string | null {
  if (!navigator.mediaDevices?.getUserMedia) {
    return window.isSecureContext
      ? "This browser can't use the camera. Try the latest Chrome, Safari or Firefox."
      : 'The camera only works on a secure (https://) address. Open the link exactly as it was sent to you.'
  }
  if (typeof MediaRecorder === 'undefined') {
    return "This browser can't record video. Try the latest Chrome, Safari or Firefox."
  }
  return null
}

function cameraErrorMessage(name: string): string {
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Camera and microphone access was blocked. Allow them for this page (look for the camera icon in the address bar, or your browser settings) and try again.'
    case 'NotFoundError':
      return "We couldn't find a camera and microphone on this device."
    case 'NotReadableError':
    case 'AbortError':
      return 'Your camera or microphone is busy in another app (a video call?). Close it and try again.'
    default:
      return "Couldn't start your camera. Please try again."
  }
}

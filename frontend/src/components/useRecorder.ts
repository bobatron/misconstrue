import { useCallback, useEffect, useRef, useState } from 'react'

const MIME_TYPES = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4']
export const MAX_SECONDS = 30

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

  const start = useCallback(async () => {
    setError('')
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: { echoCancellation: true, noiseSuppression: true },
      })
      setStream(s)
      return s
    } catch (err) {
      const name = (err as DOMException).name
      setError(
        name === 'NotAllowedError'
          ? 'We need your camera and microphone. Allow access in your browser settings and try again.'
          : 'Could not start your camera. Is another app using it?',
      )
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
        r.start(250)
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

  useEffect(() => () => stream?.getTracks().forEach((t) => t.stop()), [stream])

  return { stream, recording, seconds, error, start, record, stop }
}

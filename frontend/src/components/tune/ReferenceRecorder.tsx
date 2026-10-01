import { useEffect, useRef, useState } from 'react'
import { deleteReference, referenceUrl, saveReference } from '../../tuneApi'

const TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']

type Props = { recordingId: number; target: string; hasReference: boolean; onChange: () => void }

/** Record yourself saying the target sentence the way the finished video should sound. */
export default function ReferenceRecorder({ recordingId, target, hasReference, onChange }: Props) {
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [draft, setDraft] = useState<{ blob: Blob; url: string } | null>(null)
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0) // bust the audio cache after saving
  const recorder = useRef<MediaRecorder | null>(null)

  useEffect(() => {
    if (!recording) return
    const id = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [recording])

  async function start() {
    setError('')
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t))
      const r = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const chunks: Blob[] = []
      r.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop()) // mic off
        const blob = new Blob(chunks, { type: r.mimeType || 'audio/webm' })
        setDraft({ blob, url: URL.createObjectURL(blob) })
        setRecording(false)
      }
      r.start()
      recorder.current = r
      setSeconds(0)
      setRecording(true)
    } catch {
      setError('Microphone not available: allow it for this page and try again.')
    }
  }

  async function save() {
    if (!draft) return
    try {
      await saveReference(recordingId, draft.blob)
      URL.revokeObjectURL(draft.url)
      setDraft(null)
      setVersion((v) => v + 1)
      onChange()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function remove() {
    await deleteReference(recordingId)
    onChange()
  }

  return (
    <div className="reference">
      <p className="small"><strong>Reference voice</strong> <span className="muted">(one per link)</span></p>
      <p className="muted small">Say “{target}” the way the finished video should sound: speed, rhythm and all.</p>
      {recording ? (
        <button className="stop" onClick={() => recorder.current?.stop()}>■ Stop ({seconds}s)</button>
      ) : draft ? (
        <div className="tune-toolbar">
          <audio src={draft.url} controls />
          <button onClick={save}>Save</button>
          <button className="secondary" onClick={() => { URL.revokeObjectURL(draft.url); setDraft(null) }}>Discard</button>
        </div>
      ) : (
        <div className="tune-toolbar">
          {hasReference && <audio key={version} src={`${referenceUrl(recordingId)}?v=${version}`} controls />}
          <button className={hasReference ? 'secondary' : ''} onClick={start}>
            ● {hasReference ? 'Re-record' : 'Record reference'}
          </button>
          {hasReference && <button className="link tiny" onClick={remove}>delete</button>}
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  )
}

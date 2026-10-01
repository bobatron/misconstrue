import { useCallback, useEffect, useState } from 'react'
import { type Render, type TuneRecording, createRender, deleteRender, getRenders } from '../../tuneApi'
import VersionedVideo from '../VersionedVideo'

const pct = (v: number | null) => (v == null ? '–' : `${Math.round(v * 100)}%`)

function RenderCard({ r, onDelete }: { r: Render; onDelete: () => void }) {
  const busy = r.status === 'queued' || r.status === 'processing'
  const settings = Object.entries(r.settings)
  return (
    <article className="card render">
      <div className="render-head">
        <strong>#{r.id}</strong>
        <span className="muted small">{new Date(r.created_at).toLocaleTimeString()}</span>
        {!busy && <button className="link tiny" onClick={onDelete}>delete</button>}
      </div>
      {r.video_url ? (
        <VersionedVideo className="render-video" plainUrl={r.video_url} partyUrl={r.party_video_url} download={false} />
      ) : (
        <div className="render-video placeholder">
          {busy ? <div className="spinner" /> : <p className="small">{r.message || r.status}</p>}
        </div>
      )}
      {r.status === 'done' && (
        <p className="scores">
          <span title="Target words Whisper heard correctly">words <b>{pct(r.clarity)}</b></span>
          <span title="Target sounds Whisper heard correctly">sounds <b>{pct(r.sounds)}</b></span>
          <span className="muted">{r.timings.total?.toFixed(1)}s</span>
        </p>
      )}
      {r.heard && <p className="muted small">heard: “{r.heard}”</p>}
      {r.status === 'needs_retake' && <p className="small">Retake check would reject this take.</p>}
      <div className="chips">
        {settings.length ? settings.map(([k, v]) => <span key={k} className="chip">{k}={v}</span>) : <span className="chip">all defaults</span>}
      </div>
    </article>
  )
}

type Props = { recording: TuneRecording; hasPending: boolean; onRendered: () => void }

export default function RecordingPanel({ recording, hasPending, onRendered }: Props) {
  const [renders, setRenders] = useState<Render[]>([])
  const [error, setError] = useState('')

  const load = useCallback(() => getRenders(recording.id).then(setRenders).catch((e) => setError(e.message)), [recording.id])

  useEffect(() => {
    void load()
  }, [load])

  // Poll while anything is still rendering.
  const working = renders.some((r) => r.status === 'queued' || r.status === 'processing')
  useEffect(() => {
    if (!working) return
    const id = setInterval(() => {
      void load().then(() => onRendered())
    }, 1000)
    return () => clearInterval(id)
  }, [working, load, onRendered])

  async function render() {
    setError('')
    try {
      await createRender(recording.id)
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <section className="tune-recording">
      <div className="card">
        <p className="small muted">Recording #{recording.id} · {recording.status}</p>
        <p><span className="muted small">Target:</span> {recording.target_text}</p>
        <p><span className="muted small">They read:</span> {recording.masked_text}</p>
        <div className="tune-toolbar">
          <button onClick={render} disabled={working}>Re-render with current settings</button>
          {hasPending && <span className="small notice-inline">You have unapplied changes: apply them first.</span>}
        </div>
        {!recording.analysed && (
          <p className="muted small">The first re-render analyses the recording (about 20 s). After that each takes a couple of seconds.</p>
        )}
        {error && <p className="error small">{error}</p>}
      </div>

      <div className="render-grid">
        {recording.original_video_url && (
          <article className="card render">
            <div className="render-head"><strong>Original</strong><span className="muted small">as User 2 saw it</span></div>
            <VersionedVideo className="render-video" plainUrl={recording.original_video_url} partyUrl={recording.original_party_video_url} download={false} />
          </article>
        )}
        {renders.map((r) => (
          <RenderCard key={r.id} r={r} onDelete={() => deleteRender(r.id).then(load)} />
        ))}
      </div>
    </section>
  )
}

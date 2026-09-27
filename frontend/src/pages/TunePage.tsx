import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import RecordingPanel from '../components/tune/RecordingPanel'
import SettingsPanel from '../components/tune/SettingsPanel'
import { type SettingsGroup, type TuneRecording, getRecordings, getSettings } from '../tuneApi'

export default function TunePage() {
  const [groups, setGroups] = useState<SettingsGroup[]>([])
  const [recordings, setRecordings] = useState<TuneRecording[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [pending, setPending] = useState<Record<string, string | number>>({})
  const [error, setError] = useState('')

  const loadRecordings = useCallback(
    () => getRecordings().then((rs) => {
      setRecordings(rs)
      setSelected((cur) => cur ?? rs[0]?.id ?? null)
    }),
    [],
  )

  useEffect(() => {
    getSettings().then((s) => setGroups(s.groups)).catch((e) => setError(e.message))
    loadRecordings().catch((e) => setError(e.message))
  }, [loadRecordings])

  const recording = recordings.find((r) => r.id === selected)

  return (
    <main className="tune-page">
      <header className="tune-header">
        <Link to="/" className="logo small-logo">misconstrue</Link>
        <h1>Tuning</h1>
        <p className="muted small">Change settings, re-render a saved recording, compare. Only works on this computer.</p>
      </header>
      {error && <p className="error">{error}</p>}
      <div className="tune-layout">
        <SettingsPanel groups={groups} onSaved={setGroups} pending={pending} setPending={setPending} />
        <div>
          <label className="small" htmlFor="rec">Recording</label>
          <select id="rec" className="wide-select" value={selected ?? ''} onChange={(e) => setSelected(Number(e.target.value))}>
            {recordings.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} · {r.status === 'done' ? '✓' : '✗'} · {r.target_text.slice(0, 60)}
                {r.renders ? ` · ${r.renders} render${r.renders > 1 ? 's' : ''}` : ''}
              </option>
            ))}
          </select>
          {recording && (
            <RecordingPanel
              key={recording.id}
              recording={recording}
              hasPending={Object.keys(pending).length > 0}
              onRendered={loadRecordings}
            />
          )}
        </div>
      </div>
    </main>
  )
}

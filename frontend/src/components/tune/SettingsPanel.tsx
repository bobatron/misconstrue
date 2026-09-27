import { useState } from 'react'
import { type Setting, type SettingsGroup, SettingsErrors, resetSettings, updateSettings } from '../../tuneApi'

type Props = {
  groups: SettingsGroup[]
  onSaved: (groups: SettingsGroup[]) => void
  pending: Record<string, string | number>
  setPending: (p: Record<string, string | number>) => void
}

const ACRONYMS = new Set(['LLM', 'MFA', 'WER', 'FPS', 'URL', 'DIR', 'SR'])
const UNITS: Record<string, string> = { MS: '(ms)', S: '(s)', MB: '(MB)' }

/** CROSSFADE_MS -> "Crossfade (ms)", LLM_PROVIDER -> "LLM provider" */
function label(name: string) {
  const words = name.split('_')
  const unit = UNITS[words[words.length - 1]]
  if (unit) words.pop()
  const text = words
    .map((w, i) => (ACRONYMS.has(w) ? w : i === 0 ? w[0] + w.slice(1).toLowerCase() : w.toLowerCase()))
    .join(' ')
  return unit ? `${text} ${unit}` : text
}

function Control({ s, value, onChange }: { s: Setting; value: string | number; onChange: (v: string | number) => void }) {
  if (!s.editable) return <code className="readonly">{String(s.value)}</code>
  if (s.type === 'choice') {
    return (
      <select value={String(value)} onChange={(e) => onChange(e.target.value)}>
        {s.choices?.map((c) => <option key={c}>{c}</option>)}
      </select>
    )
  }
  if (s.type === 'int' || s.type === 'float') {
    const num = (v: string) => (s.type === 'int' ? parseInt(v, 10) : parseFloat(v))
    return (
      <div className="number-control">
        <input
          type="range" min={s.min ?? 0} max={s.max ?? 100} step={s.step} value={Number(value)}
          onChange={(e) => onChange(num(e.target.value))}
        />
        <input
          type="number" min={s.min ?? undefined} max={s.max ?? undefined} step={s.step} value={value}
          onChange={(e) => e.target.value !== '' && onChange(num(e.target.value))}
        />
      </div>
    )
  }
  return <input type="text" value={String(value)} onChange={(e) => onChange(e.target.value)} />
}

export default function SettingsPanel({ groups, onSaved, pending, setPending }: Props) {
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const count = Object.keys(pending).length

  function change(s: Setting, v: string | number) {
    const next = { ...pending }
    if (v === s.value) delete next[s.name]
    else next[s.name] = v
    setPending(next)
    setErrors((e) => ({ ...e, [s.name]: '' }))
  }

  async function run(action: () => Promise<{ groups: SettingsGroup[] }>, done: string) {
    setBusy(true)
    setMessage('')
    try {
      onSaved((await action()).groups)
      setPending({})
      setErrors({})
      setMessage(done)
    } catch (e) {
      if (e instanceof SettingsErrors) setErrors(e.errors)
      else setMessage((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const tunedCount = groups.flatMap((g) => g.settings).filter((s) => s.source === 'tuning page').length

  return (
    <section className="tune-settings">
      <div className="tune-toolbar">
        <button disabled={!count || busy} onClick={() => run(() => updateSettings(pending), 'Saved: applies to the next video.')}>
          {count ? `Apply ${count} change${count > 1 ? 's' : ''}` : 'No changes'}
        </button>
        {count > 0 && <button className="secondary" onClick={() => { setPending({}); setErrors({}) }}>Discard</button>}
        <button
          className="link" disabled={!tunedCount || busy}
          onClick={() => run(resetSettings, 'Back to defaults (plus anything in .env).')}
        >
          Reset all ({tunedCount})
        </button>
      </div>
      {message && <p className="muted small">{message}</p>}

      {groups.map((g) => (
        <details key={g.id} className="card tune-group" open={g.id !== 'system'}>
          <summary>
            <strong>{g.title}</strong>
            <span className="muted small"> · affects: {g.affects}</span>
          </summary>
          {g.settings.map((s) => {
            const value = pending[s.name] ?? s.value ?? ''
            const differs = value !== s.default
            return (
              <div key={s.name} className={`setting ${s.name in pending ? 'pending' : ''}`}>
                <div className="setting-head">
                  <label title={s.name}>{label(s.name)}</label>
                  {s.source !== 'default' && <span className={`badge ${s.source === 'tuning page' ? 'accent' : ''}`}>{s.source}</span>}
                  {s.editable && differs && (
                    <button className="link tiny" onClick={() => change(s, s.default ?? '')}>default: {String(s.default)}</button>
                  )}
                </div>
                <Control s={s} value={value} onChange={(v) => change(s, v)} />
                <p className="muted small">{s.description}</p>
                {errors[s.name] && <p className="error small">{errors[s.name]}</p>}
              </div>
            )
          })}
        </details>
      ))}
    </section>
  )
}

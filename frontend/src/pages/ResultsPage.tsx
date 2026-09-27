import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Results, getResults } from '../api'
import CopyField from '../components/CopyField'

const POLL_MS = 4000

const STATUS_TEXT: Record<string, string> = {
  uploaded: 'Just recorded, waiting to be processed…',
  processing: 'Being cut up right now…',
  needs_retake: 'They missed some words and were asked to try again.',
  failed: 'Something went wrong with this attempt.',
}

export default function ResultsPage() {
  const { token = '' } = useParams()
  const [results, setResults] = useState<Results | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(
    () => getResults(token).then(setResults).catch((e) => setError(e.message)),
    [token],
  )

  useEffect(() => {
    void load()
    const id = setInterval(load, POLL_MS) // keep checking until a video arrives
    return () => clearInterval(id)
  }, [load])

  if (error) {
    return (
      <main className="page">
        <h1 className="logo">misconstrue</h1>
        <section className="card"><p>{error}</p><Link to="/">Make your own</Link></section>
      </main>
    )
  }
  if (!results) return <main className="page"><p className="muted">Loading…</p></main>

  const done = results.recordings.filter((r) => r.video_url)
  const inProgress = results.recordings.filter((r) => !r.video_url)
  const latest = inProgress[0]

  return (
    <main className="page">
      <h1 className="logo">misconstrue</h1>
      <p className="tagline">You asked them to say:</p>
      <blockquote className="masked">“{results.target_text}”</blockquote>

      {done.length === 0 && (
        <section className="card center">
          <div className="spinner" />
          <h2>{latest ? STATUS_TEXT[latest.status] ?? 'Working on it…' : 'Waiting for your friend to record'}</h2>
          <p className="muted small">This page checks for new videos by itself.</p>
        </section>
      )}

      {done.map((r, i) => (
        <section key={r.id} className="card">
          <h2>{i === 0 ? 'misconstrued!' : 'An earlier take'}</h2>
          <video className="result-video" src={r.video_url!} controls playsInline preload="metadata" />
          <div className="button-row">
            <a className="button secondary" href={r.video_url!} download="misconstrued.mp4">Download</a>
          </div>
          <p className="muted small">{new Date(r.created_at).toLocaleString()}</p>
        </section>
      ))}

      <section className="card">
        <h2>{done.length ? 'Send it to someone else?' : 'Not sent it yet?'}</h2>
        <p className="muted small">This is the link for your friend (not this page):</p>
        <CopyField value={`${window.location.origin}/c/${results.slug}`} label="Link for your friend" />
        <p className="muted small">They'll read: “{results.masked_text}”</p>
      </section>
      <Link className="link" to="/">Make another</Link>
    </main>
  )
}

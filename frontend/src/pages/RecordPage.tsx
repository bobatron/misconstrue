import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Challenge, getChallenge, getRecording, uploadRecording } from '../api'
import { MAX_SECONDS, useRecorder } from '../components/useRecorder'

type Stage =
  | { name: 'loading' }
  | { name: 'missing'; message: string }
  | { name: 'intro' }
  | { name: 'ready'; retake?: { message: string; missing: number[] } }
  | { name: 'recording' }
  | { name: 'review'; blob: Blob; url: string }
  | { name: 'processing' }
  | { name: 'done'; videoUrl: string; target: string }
  | { name: 'failed'; message: string }

export default function RecordPage() {
  const { slug = '' } = useParams()
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const [stage, setStage] = useState<Stage>({ name: 'loading' })
  const rec = useRecorder()
  const preview = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    getChallenge(slug)
      .then((c) => {
        setChallenge(c)
        setStage({ name: 'intro' })
      })
      .catch((e) => setStage({ name: 'missing', message: e.message }))
  }, [slug])

  // Keep the live camera attached to the preview element whenever it's on screen.
  useEffect(() => {
    if (preview.current && rec.stream && preview.current.srcObject !== rec.stream) {
      preview.current.srcObject = rec.stream
    }
  })

  async function startRecording() {
    setStage({ name: 'recording' })
    const blob = await rec.record()
    setStage({ name: 'review', blob, url: URL.createObjectURL(blob) })
  }

  async function submit(blob: Blob) {
    setStage({ name: 'processing' })
    try {
      const { recording_id } = await uploadRecording(slug, blob)
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500))
        const s = await getRecording(recording_id)
        if (s.status === 'done') return setStage({ name: 'done', videoUrl: s.video_url, target: s.target_text })
        if (s.status === 'needs_retake')
          return setStage({ name: 'ready', retake: { message: s.message, missing: s.missing_tokens } })
        if (s.status === 'failed') return setStage({ name: 'failed', message: s.message })
      }
    } catch (e) {
      setStage({ name: 'failed', message: (e as Error).message })
    }
  }

  const teleprompter = (missing: number[] = []) => (
    <p className="teleprompter">
      {challenge?.tokens.map((t, i) => (
        <span key={i} className={missing.includes(i) ? 'missed' : undefined}>
          {t}{' '}
        </span>
      ))}
    </p>
  )

  switch (stage.name) {
    case 'loading':
      return <main className="page"><p className="muted">Loading…</p></main>

    case 'missing':
      return (
        <main className="page">
          <h1 className="logo">misconstrue</h1>
          <section className="card"><p>{stage.message}</p><Link to="/">Make your own</Link></section>
        </main>
      )

    case 'intro':
      return (
        <main className="page">
          <h1 className="logo">misconstrue</h1>
          <section className="card">
            <h2>A friend needs your voice</h2>
            <p>Read one sentence out loud on camera. It takes about ten seconds.</p>
            {rec.error && <p className="error">{rec.error}</p>}
            <button className="wide" onClick={async () => (await rec.start()) && setStage({ name: 'ready' })}>
              Turn on camera
            </button>
          </section>
        </main>
      )

    case 'ready':
    case 'recording': {
      const recording = stage.name === 'recording'
      const retake = stage.name === 'ready' ? stage.retake : undefined
      return (
        <main className="page">
          {retake && <p className="notice">{retake.message}</p>}
          <div className="stage">
            <video ref={preview} className="camera mirrored" autoPlay muted playsInline />
            {recording && <span className="rec-dot">● {MAX_SECONDS - rec.seconds}s</span>}
          </div>
          <p className="muted small">{recording ? 'Read this out loud, clearly:' : 'When you press record, read this out loud:'}</p>
          {teleprompter(retake?.missing)}
          {recording ? (
            <button className="wide stop" onClick={rec.stop}>Stop</button>
          ) : (
            <button className="wide record" onClick={startRecording}>
              ● Record
            </button>
          )}
        </main>
      )
    }

    case 'review':
      return (
        <main className="page">
          <div className="stage"><video className="camera mirrored" src={stage.url} controls playsInline /></div>
          <p className="muted small">Happy with it?</p>
          <div className="button-row">
            <button className="secondary" onClick={() => setStage({ name: 'ready' })}>Retake</button>
            <button onClick={() => submit(stage.blob)}>Submit</button>
          </div>
        </main>
      )

    case 'processing':
      return (
        <main className="page">
          <section className="card center">
            <div className="spinner" />
            <h2>Processing…</h2>
            <p className="muted">Checking your recording. This takes about a minute.</p>
          </section>
        </main>
      )

    case 'done':
      return (
        <main className="page">
          <h1 className="logo">misconstrued!</h1>
          <p className="tagline">Here's what you <em>actually</em> said:</p>
          <div className="stage"><video className="camera" src={stage.videoUrl} controls autoPlay playsInline /></div>
          <blockquote className="masked">“{stage.target}”</blockquote>
          <div className="button-row">
            <a className="button secondary" href={stage.videoUrl} download="misconstrued.mp4">Download</a>
            <Link className="button" to="/">Get revenge</Link>
          </div>
        </main>
      )

    case 'failed':
      return (
        <main className="page">
          <section className="card">
            <p className="error">{stage.message}</p>
            <button className="wide" onClick={() => setStage({ name: 'ready' })}>Try again</button>
          </section>
        </main>
      )
  }
}

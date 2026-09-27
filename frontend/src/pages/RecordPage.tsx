import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Challenge, getChallenge, getRecording, uploadRecording } from '../api'
import { type PromptTiming, usePrompter } from '../components/usePrompter'
import { MAX_SECONDS, useRecorder } from '../components/useRecorder'

type Retake = { message: string; missing: number[] }

type Stage =
  | { name: 'loading' }
  | { name: 'missing'; message: string }
  | { name: 'intro' }
  | { name: 'ready'; retake?: Retake }
  | { name: 'recording'; retake?: Retake }
  | { name: 'review'; blob: Blob; url: string; retake?: Retake }
  | { name: 'processing' }
  | { name: 'done'; videoUrl: string; target: string }
  | { name: 'failed'; message: string }

export default function RecordPage() {
  const { slug = '' } = useParams()
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const [stage, setStage] = useState<Stage>({ name: 'loading' })
  const rec = useRecorder()
  const preview = useRef<HTMLVideoElement>(null)
  const timings = useRef<PromptTiming[]>([])
  const stopRecording = rec.stop
  const onPromptsDone = useCallback(
    (t: PromptTiming[]) => {
      timings.current = t
      stopRecording()
    },
    [stopRecording],
  )
  const prompter = usePrompter({
    prompts: challenge?.prompts ?? [],
    stream: rec.stream,
    active: stage.name === 'recording',
    silenceMs: challenge?.prompter.advance_silence_ms ?? 600,
    hintAfterS: challenge?.prompter.hint_after_s ?? 6,
    onFinish: onPromptsDone,
  })

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

  async function startRecording(retake?: Retake) {
    timings.current = []
    setStage({ name: 'recording', retake })
    const blob = await rec.record()
    setStage({ name: 'review', blob, url: URL.createObjectURL(blob), retake })
  }

  /** Camera back on (no permission prompt the second time), then back to the record screen. */
  async function backToRecording(retake?: Retake) {
    if (await rec.start()) setStage({ name: 'ready', retake })
    else setStage({ name: 'intro' })
  }

  async function submit(blob: Blob, url: string) {
    rec.release()
    URL.revokeObjectURL(url)
    setStage({ name: 'processing' })
    try {
      const { recording_id } = await uploadRecording(slug, blob, timings.current)
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500))
        const s = await getRecording(recording_id)
        if (s.status === 'done') return setStage({ name: 'done', videoUrl: s.video_url, target: s.target_text })
        if (s.status === 'needs_retake')
          return backToRecording({ message: s.message, missing: s.missing_tokens })
        if (s.status === 'failed') return setStage({ name: 'failed', message: s.message })
      }
    } catch (e) {
      setStage({ name: 'failed', message: (e as Error).message })
    }
  }

  /** Prompts containing words the check said were missed. */
  const missedPrompts = (missing: number[] = []) =>
    new Set((challenge?.prompts ?? []).flatMap((p, i) => (p.tokens.some((t) => missing.includes(t)) ? [i] : [])))

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
            <p>Some words will pop up on screen, a few at a time. Just say them out loud. It takes about half a minute.</p>
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
      const retake = stage.retake
      const prompts = challenge?.prompts ?? []
      const flagged = missedPrompts(retake?.missing)
      const current = prompts[prompter.index]
      return (
        <main className="page">
          {retake && !recording && (
            <p className="notice">
              {retake.message}
              {flagged.size > 0 && ' Those words are marked when they come up.'}
            </p>
          )}
          <div className="stage">
            <video ref={preview} className="camera mirrored" autoPlay muted playsInline />
            {recording && <span className="rec-dot">● {MAX_SECONDS - rec.seconds}s</span>}
            {recording && (
              <div className="prompter" aria-live="polite">
                {prompter.phase === 'countdown' && <p className="prompt-countdown">{prompter.countdown}</p>}
                {prompter.phase === 'prompting' && current && (
                  <>
                    {flagged.has(prompter.index) && <span className="prompt-flag">say this one clearly</span>}
                    <p className={`prompt-text ${prompter.speaking ? 'speaking' : ''}`}>{current.text}</p>
                    {prompts[prompter.index + 1] && <p className="prompt-next">{prompts[prompter.index + 1].text}</p>}
                  </>
                )}
                {prompter.phase === 'done' && <p className="prompt-text">✓</p>}
                <div className="prompt-footer">
                  <span className="level" title="Microphone level">
                    <span style={{ width: `${Math.round(prompter.level * 100)}%` }} />
                  </span>
                  {prompter.phase === 'prompting' && <span>{prompter.index + 1} / {prompts.length}</span>}
                </div>
              </div>
            )}
          </div>
          {recording ? (
            <>
              <p className="muted small center-text">
                {prompter.hint ? "Say it out loud, or tap Next if you already have." : 'Say each one clearly, then pause. It moves on by itself.'}
              </p>
              <div className="button-row">
                <button className="secondary" onClick={prompter.back} disabled={prompter.phase !== 'prompting' || prompter.index === 0}>← Back</button>
                <button className={prompter.hint ? 'pulse' : 'secondary'} onClick={prompter.next} disabled={prompter.phase !== 'prompting'}>Next →</button>
              </div>
              <button className="wide stop" onClick={rec.stop}>Stop</button>
            </>
          ) : (
            <>
              <p className="muted small">
                When you press record, words appear on the video a few at a time. Say each group out loud, clearly,
                then pause: it moves on by itself. ({prompts.length} to go)
              </p>
              <button className="wide record" onClick={() => startRecording(retake)}>● Record</button>
            </>
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
            <button className="secondary" onClick={() => setStage({ name: 'ready', retake: stage.retake })}>Retake</button>
            <button onClick={() => submit(stage.blob, stage.url)}>Submit</button>
          </div>
        </main>
      )

    case 'processing':
      return (
        <main className="page">
          <section className="card center">
            <div className="spinner" />
            <h2>Processing…</h2>
            <p className="muted">Checking your recording. This takes about 20 seconds.</p>
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
            <button className="wide" onClick={() => backToRecording()}>Try again</button>
          </section>
        </main>
      )
  }
}

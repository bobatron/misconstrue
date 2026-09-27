import { useState } from 'react'
import { createChallenge } from '../api'

export default function CreatePage() {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ url: string; masked: string } | null>(null)
  const [copied, setCopied] = useState(false)
  const [peek, setPeek] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const ch = await createChallenge(text)
      setResult({ url: `${window.location.origin}/c/${ch.slug}`, masked: ch.masked_text })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    if (!result) return
    await navigator.clipboard.writeText(result.url)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function share() {
    if (result) navigator.share?.({ title: 'Read this out for me?', url: result.url })
  }

  if (result) {
    return (
      <main className="page">
        <h1 className="logo">misconstrue</h1>
        <section className="card">
          <h2>Your link is ready</h2>
          <p className="muted">Send it to a friend. They'll be asked to read an innocent-looking sentence…</p>
          <div className="share-row">
            <input className="share-url" readOnly value={result.url} onFocus={(e) => e.target.select()} />
            <button onClick={copy}>{copied ? 'Copied!' : 'Copy'}</button>
          </div>
          {'share' in navigator && (
            <button className="secondary wide" onClick={share}>
              Share…
            </button>
          )}
          <button className="link" onClick={() => setPeek(!peek)}>
            {peek ? 'Hide' : 'Peek at'} what they'll read
          </button>
          {peek && <blockquote className="masked">{result.masked}</blockquote>}
        </section>
        <button className="link" onClick={() => { setResult(null); setText('') }}>
          Make another
        </button>
      </main>
    )
  }

  return (
    <main className="page">
      <h1 className="logo">misconstrue</h1>
      <p className="tagline">Put words in your friend's mouth.</p>
      <form className="card" onSubmit={submit}>
        <label htmlFor="sentence">What do you want them to say?</label>
        <textarea
          id="sentence"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="hello sir this is not what I originally said"
          maxLength={200}
          rows={3}
          autoFocus
        />
        {error && <p className="error">{error}</p>}
        <button className="wide" disabled={busy || !text.trim()}>
          {busy ? 'Writing a disguise… (about 15 s)' : 'Create link'}
        </button>
      </form>
      <p className="muted small">
        We'll write a different sentence that secretly contains all the sounds of yours. When your friend reads it on
        camera, we cut it up to make them say your sentence.
      </p>
    </main>
  )
}

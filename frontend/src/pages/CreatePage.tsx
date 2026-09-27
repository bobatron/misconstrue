import { useState } from 'react'
import { Link } from 'react-router-dom'
import { createChallenge } from '../api'
import CopyField from '../components/CopyField'
import { type MyLink, forgetLink, loadLinks, rememberLink } from '../myLinks'

export default function CreatePage() {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ shareUrl: string; resultsPath: string; masked: string } | null>(null)
  const [peek, setPeek] = useState(false)
  const [links, setLinks] = useState<MyLink[]>(loadLinks)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const ch = await createChallenge(text)
      rememberLink({ slug: ch.slug, token: ch.results_token, text: text.trim(), created: new Date().toISOString() })
      setLinks(loadLinks())
      setResult({
        shareUrl: `${window.location.origin}/c/${ch.slug}`,
        resultsPath: `/r/${ch.results_token}`,
        masked: ch.masked_text,
      })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function share() {
    if (result) navigator.share?.({ title: 'Read this out for me?', url: result.shareUrl })
  }

  if (result) {
    return (
      <main className="page">
        <h1 className="logo">misconstrue</h1>
        <section className="card">
          <h2>1. Send this to a friend</h2>
          <p className="muted">They'll be asked to say a few "calibration" words, one at a time…</p>
          <CopyField value={result.shareUrl} label="Link for your friend" />
          {'share' in navigator && (
            <button className="secondary wide" onClick={share}>
              Share…
            </button>
          )}
          <button className="link" onClick={() => setPeek(!peek)}>
            {peek ? 'Hide' : 'Peek at'} the words they'll say
          </button>
          {peek && <blockquote className="masked">{result.masked}</blockquote>}
        </section>
        <section className="card">
          <h2>2. Watch the result</h2>
          <p className="muted">
            This one's just for you: it shows the video once your friend has recorded. Don't send it to them.
          </p>
          <CopyField value={`${window.location.origin}${result.resultsPath}`} label="Your results link" />
          <Link className="button secondary" to={result.resultsPath}>Open results</Link>
          <p className="muted small">We'll also remember it in this browser, below "Your links".</p>
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
          {busy ? 'Creating…' : 'Create link'}
        </button>
      </form>
      <p className="muted small">
        We pick different words that secretly contain all the sounds of yours. When your friend says them on camera,
        we cut them up to make them say your sentence.
      </p>
      {links.length > 0 && (
        <section className="card">
          <h2>Your links</h2>
          <ul className="my-links">
            {links.map((l) => (
              <li key={l.token}>
                <Link to={`/r/${l.token}`}>“{l.text}”</Link>
                <span className="muted small"> · {new Date(l.created).toLocaleDateString()}</span>
                <button className="link tiny" onClick={() => { forgetLink(l.token); setLinks(loadLinks()) }}>forget</button>
              </li>
            ))}
          </ul>
          <p className="muted small">Only saved in this browser.</p>
        </section>
      )}
    </main>
  )
}

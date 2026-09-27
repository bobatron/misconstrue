import { useState } from 'react'

/** A read-only link with a Copy button. */
export default function CopyField({ value, label }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard blocked: the field is selectable, so the link can still be copied by hand.
    }
  }
  return (
    <div className="share-row">
      <input className="share-url" readOnly value={value} aria-label={label} onFocus={(e) => e.target.select()} />
      <button onClick={copy}>{copied ? 'Copied!' : 'Copy'}</button>
    </div>
  )
}

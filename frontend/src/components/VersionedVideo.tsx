import { useState } from 'react'

type Props = {
  plainUrl: string
  partyUrl?: string | null
  className?: string
  download?: boolean
}

/** The finished video: party version (music, effects) by default, with a switch to the plain one. */
export default function VersionedVideo({ plainUrl, partyUrl, className, download = true }: Props) {
  const [party, setParty] = useState(Boolean(partyUrl))
  const src = party && partyUrl ? partyUrl : plainUrl
  return (
    <div className="versioned-video">
      {partyUrl && (
        <div className="version-switch" role="tablist" aria-label="Version">
          <button role="tab" aria-selected={party} className={party ? 'on' : ''} onClick={() => setParty(true)}>
            🎵 Party
          </button>
          <button role="tab" aria-selected={!party} className={!party ? 'on' : ''} onClick={() => setParty(false)}>
            Plain
          </button>
        </div>
      )}
      <video key={src} className={className} src={src} controls playsInline preload="metadata" autoPlay={false} />
      {download && (
        <a className="button secondary" href={src} download={party ? 'misconstrued-party.mp4' : 'misconstrued.mp4'}>
          Download {partyUrl ? (party ? 'party version' : 'plain version') : ''}
        </a>
      )}
    </div>
  )
}

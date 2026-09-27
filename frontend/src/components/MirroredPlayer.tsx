import { useRef, useState } from 'react'

const fmt = (s: number) => (Number.isFinite(s) ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '–:––')

/**
 * Plays a recording mirrored (as you saw yourself while recording) with our own controls.
 * The browser's built-in controls can't be used: they're part of the video, so mirroring the
 * video would mirror them too.
 */
export default function MirroredPlayer({ src, onShape }: { src: string; onShape?: (aspect: number) => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const fixingDuration = useRef(false)

  function onLoadedMetadata(e: React.SyntheticEvent<HTMLVideoElement>) {
    const v = e.currentTarget
    if (v.videoWidth && v.videoHeight) onShape?.(v.videoWidth / v.videoHeight)
    if (Number.isFinite(v.duration)) {
      setDuration(v.duration)
    } else {
      // Chrome doesn't know a fresh MediaRecorder video's length until it has read to the end:
      // jump far ahead, and the real duration becomes known.
      fixingDuration.current = true
      v.currentTime = 1e9
    }
  }

  function onTimeUpdate(e: React.SyntheticEvent<HTMLVideoElement>) {
    const v = e.currentTarget
    if (fixingDuration.current) {
      if (Number.isFinite(v.duration)) {
        fixingDuration.current = false
        setDuration(v.duration)
        v.currentTime = 0
      }
      return
    }
    setTime(v.currentTime)
  }

  function toggle() {
    const v = video.current
    if (!v) return
    if (v.paused) {
      if (v.ended) v.currentTime = 0
      void v.play()
    } else {
      v.pause()
    }
  }

  function seek(e: React.ChangeEvent<HTMLInputElement>) {
    const v = video.current
    if (!v) return
    v.currentTime = Number(e.target.value)
    setTime(v.currentTime)
  }

  return (
    <>
      <video
        ref={video}
        className="camera mirrored"
        src={src}
        playsInline
        preload="auto"
        onClick={toggle}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onLoadedMetadata={onLoadedMetadata}
        onDurationChange={(e) => Number.isFinite(e.currentTarget.duration) && setDuration(e.currentTarget.duration)}
        onTimeUpdate={onTimeUpdate}
      />
      <div className="player-controls">
        <button className="player-toggle" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? '❚❚' : '▶'}
        </button>
        <input
          className="player-seek"
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(time, duration || 0)}
          onChange={seek}
          aria-label="Position"
        />
        <span className="player-time">{fmt(time)} / {fmt(duration)}</span>
      </div>
    </>
  )
}

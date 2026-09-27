import { useCallback, useEffect, useRef, useState } from 'react'
import { VoiceActivity } from './voiceActivity'

export type Prompt = { text: string; tokens: number[] }
export type PromptTiming = {
  prompt: number
  shown_ms: number
  speech_start_ms: number | null
  speech_end_ms: number | null
  advanced: 'speech' | 'manual'
}

type Options = {
  prompts: Prompt[]
  stream: MediaStream | null
  active: boolean // true while recording
  silenceMs: number // pause after speech that moves on
  minSpeechPerWordMs: number // ...but only after this much speech per word on screen
  hintAfterS: number // no speech this long -> highlight Next
  onCountdownDone: () => void // start the actual recording now
  onFinish: (timings: PromptTiming[]) => void
}

const COUNTDOWN_MS = 1500 // measures background noise on the live mic; not part of the recording
const RECORD_LEAD_MS = 300 // recording starts this long before the first word appears
const GRACE_MS = 300 // ignore sound right after a prompt appears (tail of the previous one)
const MIN_SPEECH_MS = 120 // shorter blips (a cough, a click) aren't speech
const TICK_MS = 30
const LONG_PAUSE_MS = 2000 // after some speech, a pause this long moves on regardless

/**
 * Shows the masked sentence a few words at a time and moves on when the reader has said them:
 * speech starts, then there's a pause of `silenceMs`. Space / → = next, ← = back.
 */
export function usePrompter({
  prompts, stream, active, silenceMs, minSpeechPerWordMs, hintAfterS, onCountdownDone, onFinish,
}: Options) {
  const [phase, setPhase] = useState<'idle' | 'countdown' | 'prompting' | 'done'>('idle')
  const [countdown, setCountdown] = useState(3)
  const [index, setIndex] = useState(0)
  const [speaking, setSpeaking] = useState(false)
  const [hint, setHint] = useState(false)
  const [level, setLevel] = useState(0) // 0..1 relative to 2x the speech threshold, for the meter

  // Mutable state for the audio loop (avoids stale closures in setInterval).
  const s = useRef({
    t0: 0, index: 0, shownAt: 0, candidate: 0, speechStart: 0, lastVoice: 0, speaking: false,
    voicedMs: 0, // speech heard so far for the current prompt
    timings: [] as PromptTiming[],
  })
  const finish = useRef(onFinish)
  const countdownDone = useRef(onCountdownDone)
  useEffect(() => {
    finish.current = onFinish
    countdownDone.current = onCountdownDone
  }, [onFinish, onCountdownDone])

  const show = useCallback((i: number) => {
    const st = s.current
    st.index = i
    st.shownAt = performance.now()
    st.candidate = 0
    st.speaking = false
    st.voicedMs = 0
    setIndex(i)
    setSpeaking(false)
    setHint(false)
  }, [])

  const advance = useCallback((how: 'speech' | 'manual') => {
    const st = s.current
    if (st.index >= prompts.length) return // already finished
    const now = performance.now()
    st.timings.push({
      prompt: st.index,
      shown_ms: Math.round(st.shownAt - st.t0),
      speech_start_ms: st.speechStart ? Math.round(st.speechStart - st.t0) : null,
      // Pressing Next mid-speech: speech ends now. Otherwise: when the voice last stopped.
      speech_end_ms: st.speechStart ? Math.round((how === 'manual' && st.speaking ? now : st.lastVoice) - st.t0) : null,
      advanced: how,
    })
    st.speechStart = 0
    if (st.index + 1 >= prompts.length) {
      st.index = prompts.length // finished: the audio loop stops advancing
      st.speaking = false
      setPhase('done')
      setTimeout(() => finish.current(st.timings), 500) // a moment of tail before stopping
    } else {
      show(st.index + 1)
    }
  }, [prompts.length, show])

  const next = useCallback(() => {
    if (phase === 'prompting') advance('manual')
  }, [phase, advance])

  const back = useCallback(() => {
    if (phase === 'prompting' && s.current.index > 0) {
      s.current.timings = s.current.timings.filter((t) => t.prompt < s.current.index - 1)
      show(s.current.index - 1)
    }
  }, [phase, show])

  // Countdown (and noise calibration), then prompting with voice activity detection.
  useEffect(() => {
    if (!active || !stream) return
    const vad = new VoiceActivity(stream)
    const st = s.current
    st.t0 = performance.now()
    st.timings = []
    st.speechStart = 0
    let started = false
    let firstWordAt = 0 // when recording has had its head start

    const id = setInterval(() => {
      const now = performance.now()
      const rms = vad.level()
      setLevel(Math.min(1, rms / (vad.threshold * 2)))

      if (!started) {
        vad.sampleNoise()
        const left = COUNTDOWN_MS - (now - st.t0)
        setCountdown(Math.max(1, Math.ceil((left / COUNTDOWN_MS) * 3)))
        if (left <= 0) {
          vad.finishCalibration()
          started = true
          st.t0 = now // prompt timings are measured from the start of the recording
          firstWordAt = now + RECORD_LEAD_MS
          countdownDone.current()
        }
        return
      }
      if (firstWordAt) {
        if (now < firstWordAt) return
        firstWordAt = 0
        setPhase('prompting')
        show(0)
        return
      }
      if (st.index >= prompts.length) return
      if (now - st.shownAt < GRACE_MS) return

      // Once speaking, a slightly lower level still counts as voice (hysteresis), so the
      // quieter end of a word doesn't cut the prompt short.
      const loud = rms > (st.speaking ? vad.threshold * 0.7 : vad.threshold)
      if (loud) {
        if (!st.candidate) st.candidate = now
        if (!st.speaking && now - st.candidate >= MIN_SPEECH_MS) {
          st.speaking = true
          st.speechStart = st.speechStart || st.candidate
          setSpeaking(true)
          setHint(false)
        }
        if (st.speaking) {
          st.voicedMs += TICK_MS
          st.lastVoice = now
        }
      } else {
        st.candidate = 0
        // A pause means "done" only once enough has been said for the words on screen;
        // otherwise it's a pause between words and we keep listening. A long pause after some
        // speech means done anyway (someone who reads very quickly).
        const words = prompts[st.index]?.tokens.length ?? 1
        const saidEnough = st.voicedMs >= words * minSpeechPerWordMs
        const pause = now - st.lastVoice
        if (st.speechStart) {
          if ((pause >= silenceMs && saidEnough) || pause >= LONG_PAUSE_MS) {
            advance('speech')
          } else if (st.speaking && pause >= silenceMs) {
            st.speaking = false // wait for the rest of the prompt
            setSpeaking(false)
          }
        } else if (now - st.shownAt > hintAfterS * 1000) {
          setHint(true)
        }
      }
    }, TICK_MS)

    return () => {
      clearInterval(id)
      vad.close()
      setPhase('idle')
    }
  }, [active, stream, prompts, silenceMs, minSpeechPerWordMs, hintAfterS, show, advance])

  // Keyboard shortcuts while prompting.
  useEffect(() => {
    if (phase !== 'prompting') return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === ' ' || e.key === 'ArrowRight') {
        e.preventDefault()
        next()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        back()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase, next, back])

  // Between pressing record and the first audio tick, we're counting down.
  const shownPhase = active && phase === 'idle' ? 'countdown' : phase
  return { phase: shownPhase, countdown, index, speaking, hint, level, next, back }
}

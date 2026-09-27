/**
 * One shared AudioContext, started from a tap.
 *
 * Safari (especially on iPhone) keeps an AudioContext suspended unless it's created or resumed
 * directly inside a user gesture; a suspended one hears only silence. Call `unlockAudio()` at
 * the top of a click handler, before any `await`.
 */
let shared: AudioContext | null = null

export function unlockAudio(): AudioContext {
  shared ??= new AudioContext()
  if (shared.state === 'suspended') void shared.resume()
  return shared
}

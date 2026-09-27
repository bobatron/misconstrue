/**
 * Microphone loudness, measured in the browser (nothing is sent anywhere).
 * Calibrates to the room's background noise, then reports whether someone is speaking.
 */
export class VoiceActivity {
  private ctx: AudioContext
  private analyser: AnalyserNode
  private buffer: Float32Array<ArrayBuffer>
  private noise = 0.004
  private calibration: number[] = []

  constructor(stream: MediaStream) {
    this.ctx = new AudioContext()
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize = 1024
    this.ctx.createMediaStreamSource(stream).connect(this.analyser)
    this.buffer = new Float32Array(this.analyser.fftSize)
  }

  /** Current loudness (RMS, 0..1). */
  level(): number {
    this.analyser.getFloatTimeDomainData(this.buffer)
    let sum = 0
    for (const x of this.buffer) sum += x * x
    return Math.sqrt(sum / this.buffer.length)
  }

  /** Call repeatedly while the room should be quiet (the countdown). */
  sampleNoise(): void {
    this.calibration.push(this.level())
  }

  finishCalibration(): void {
    if (this.calibration.length) {
      const sorted = [...this.calibration].sort((a, b) => a - b)
      this.noise = sorted[Math.floor(sorted.length / 2)]
    }
  }

  /** Loudness that counts as speech: well above the room's background noise. */
  get threshold(): number {
    return Math.max(this.noise * 3.5, 0.012)
  }

  close(): void {
    void this.ctx.close()
  }
}

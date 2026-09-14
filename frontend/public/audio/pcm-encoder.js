// Preserve filter history and fractional position across AudioWorklet blocks.
export class StreamingPcmEncoder {
  constructor(inputRate, packetSamples = 1600, maxSamples = 960000) {
    this.rate = inputRate;
    this.packetSamples = packetSamples;
    this.maxSamples = maxSamples;
    this.outputCount = 0;
    this.packet = new ArrayBuffer(packetSamples * 2);
    this.view = new DataView(this.packet);
    this.used = 0;
    this.index = 0;
    this.nextOutput = 0;
    this.previous = 0;
    this.position = 0;
    // Windowed-sinc low-pass before downsampling, including 44.1kHz input.
    this.taps = new Float64Array(63);
    this.history = new Float32Array(63);
    const cutoff = Math.min(7200 / inputRate, 0.45);
    let sum = 0;
    for (let i = 0; i < 63; i++) {
      const x = i - 31;
      const sinc = x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x);
      const window = 0.42 - 0.5 * Math.cos(2 * Math.PI * i / 62) + 0.08 * Math.cos(4 * Math.PI * i / 62);
      this.taps[i] = sinc * window;
      sum += this.taps[i];
    }
    for (let i = 0; i < 63; i++) this.taps[i] /= sum;
  }

  push(samples, emit) {
    for (const sample of samples) {
      if (this.outputCount >= this.maxSamples) return;
      this.history[this.position] = sample;
      let filtered = 0;
      for (let tap = 0; tap < 63; tap++) {
        filtered += this.taps[tap] * this.history[(this.position - tap + 63) % 63];
      }
      this.position = (this.position + 1) % 63;
      while (this.nextOutput <= this.index && this.outputCount < this.maxSamples) {
        const fraction = Math.max(0, Math.min(1, this.nextOutput - this.index + 1));
        const value = Math.max(-1, Math.min(1, this.previous + (filtered - this.previous) * fraction));
        this.view.setInt16(this.used * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
        this.used++;
        this.outputCount++;
        this.nextOutput = this.outputCount * this.rate / 16000;
        if (this.used === this.packetSamples) {
          emit(this.packet);
          this.packet = new ArrayBuffer(this.packetSamples * 2);
          this.view = new DataView(this.packet);
          this.used = 0;
        }
      }
      this.previous = filtered;
      this.index++;
    }
  }

  flush(emit) {
    if (this.used) emit(this.packet.slice(0, this.used * 2));
    this.used = 0;
  }
}

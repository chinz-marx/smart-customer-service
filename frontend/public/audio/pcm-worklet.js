import { StreamingPcmEncoder } from './pcm-encoder.js';

class SpeechPcmProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.encoder = new StreamingPcmEncoder(sampleRate, 1600, options.processorOptions.maxSamples);
    this.stopped = false;
    this.emit = (buffer) => this.port.postMessage({ type: 'audio', buffer }, [buffer]);
    this.port.onmessage = ({ data }) => {
      if (data.type === 'finish') this.finish();
    };
  }

  finish() {
    if (this.stopped) return;
    this.stopped = true;
    this.encoder.flush(this.emit);
    // Last partial packet must precede the finish message on the FIFO port.
    this.port.postMessage({ type: 'flushed' });
  }

  process(inputs) {
    if (this.stopped) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;
    let mono = channels[0];
    if (channels.length > 1) {
      mono = new Float32Array(channels[0].length);
      for (const channel of channels) {
        for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
      }
    }
    this.encoder.push(mono, this.emit);
    if (this.encoder.outputCount >= this.encoder.maxSamples) this.finish();
    return !this.stopped;
  }
}

registerProcessor('speech-pcm', SpeechPcmProcessor);

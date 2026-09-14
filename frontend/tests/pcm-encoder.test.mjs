import test from 'node:test';
import assert from 'node:assert/strict';
import { StreamingPcmEncoder } from '../public/audio/pcm-encoder.js';

function encode(rate, input, blockSize = 128, maxSamples) {
  const encoder = new StreamingPcmEncoder(rate, 1600, maxSamples);
  const packets = [];
  const emit = (packet) => packets.push(Buffer.from(packet));
  for (let i = 0; i < input.length; i += blockSize) encoder.push(input.subarray(i, i + blockSize), emit);
  encoder.flush(emit);
  return { packets, pcm: Buffer.concat(packets) };
}

for (const rate of [16000, 44100, 48000]) {
  test(`resamples ${rate}Hz to 16000Hz with no block-boundary drift`, () => {
    const input = Float32Array.from({ length: rate + 777 }, (_, i) => 0.5 * Math.sin(2 * Math.PI * 440 * i / rate));
    const split = encode(rate, input);
    const whole = encode(rate, input, input.length);
    assert.deepEqual(split.pcm, whole.pcm);
    assert.equal(split.pcm.length / 2, Math.floor((input.length - 1) * 16000 / rate) + 1);
    assert.ok(split.packets.every((packet) => packet.length <= 3200 && packet.length % 2 === 0));
    assert.ok(split.packets.at(-1).length < 3200, 'flushes the incomplete final packet');
  });
}

test('PCM is signed little-endian and duration is bounded', () => {
  const { pcm } = encode(48000, new Float32Array(48000).fill(-2), 128, 8000);
  assert.equal(pcm.length, 16000);
  assert.equal(pcm.readInt16LE(1000), -32768);
});

test('downsampling suppresses high-frequency aliasing', () => {
  const rms = (frequency) => {
    const input = Float32Array.from({ length: 48000 }, (_, i) => 0.5 * Math.sin(2 * Math.PI * frequency * i / 48000));
    const { pcm } = encode(48000, input);
    let sum = 0;
    for (let i = 200; i < pcm.length; i += 2) sum += pcm.readInt16LE(i) ** 2;
    return Math.sqrt(sum / ((pcm.length - 200) / 2));
  };
  assert.ok(rms(12000) < rms(1000) * 0.02);
});

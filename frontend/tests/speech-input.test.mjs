import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// Run the actual composable against deterministic audio/network doubles.
// No microphone permissions or cloud calls are involved in this suite.
const source = await readFile(new URL('../src/composables/useSpeechInput.ts', import.meta.url), 'utf8');
const vue = 'data:text/javascript,' + encodeURIComponent('export const ref = value => ({value}); export const computed = fn => ({get value(){return fn()}}); export const onBeforeUnmount = () => {};');
const javascript = ts.transpile(source, { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext }).replace("from 'vue'", `from '${vue}'`);
const { useSpeechInput } = await import('data:text/javascript;base64,' + Buffer.from(javascript).toString('base64'));

function setup(getMedia) {
  const contexts = [], sockets = [], processors = [];
  const track = { stopped: false, onended: null, stop() { this.stopped = true; } };
  const media = { getTracks: () => [track] };
  const connectable = () => ({ connect(node) { return node; }, disconnect() {} });
  class Context {
    constructor() {
      contexts.push(this);
      this.closed = false;
      this.audioWorklet = { addModule: async () => {} };
      this.destination = {};
    }
    async resume() {}
    async close() { this.closed = true; }
    createMediaStreamSource() { return connectable(); }
    createGain() { return { ...connectable(), gain: { value: 1 } }; }
  }
  class Processor {
    constructor() {
      processors.push(this);
      this.port = { onmessage: null, commands: [], postMessage(message) { this.commands.push(message); } };
    }
    connect(node) { return node; }
    disconnect() {}
    emit(data) { this.port.onmessage?.({ data }); }
  }
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.bufferedAmount = 0; this.sent = []; sockets.push(this); }
    send(data) { this.sent.push(data); }
    close() { this.readyState = 3; }
    emit(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
  }
  globalThis.window = { isSecureContext: true, AudioContext: Context, AudioWorkletNode: Processor, location: { href: 'http://localhost:5173' } };
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: getMedia || (async () => media) } } });
  globalThis.AudioContext = Context;
  globalThis.AudioWorkletNode = Processor;
  globalThis.WebSocket = Socket;
  const input = { value: '已有文字' };
  const speech = useSpeechInput(input);
  const recording = async () => {
    await speech.start();
    sockets[0].onopen();
    sockets[0].emit({ type: 'ready', max_duration_seconds: 60 });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(speech.state.value, 'recording');
  };
  return { input, speech, recording, contexts, sockets, processors, media, track };
}

test('partial corrections replace text; final is awaited and audio tail precedes finish', async () => {
  const h = setup();
  try {
    await h.recording();
    const ws = h.sockets[0], processor = h.processors[0];
    ws.emit({ type: 'partial', text: '查定单' });
    ws.emit({ type: 'partial', text: '查订单进度' });
    assert.equal(h.input.value, '已有文字 查订单进度');
    h.speech.finish();
    assert.equal(h.speech.state.value, 'finishing');
    assert.equal(h.track.stopped, false);
    const tail = new ArrayBuffer(62);
    processor.emit({ type: 'audio', buffer: tail });
    processor.emit({ type: 'flushed' });
    assert.equal(ws.sent.at(-2), tail);
    assert.deepEqual(JSON.parse(ws.sent.at(-1)), { type: 'finish' });
    assert.equal(h.track.stopped, true);
    assert.equal(h.speech.active.value, true);
    ws.emit({ type: 'final', text: '查订单进度。' });
    assert.equal(h.input.value, '已有文字 查订单进度。');
    assert.equal(h.speech.active.value, false);
    assert.equal(ws.readyState, 3);
    assert.match(h.speech.notice.value, /可修改/);
  } finally { h.speech.cancel(); }
});

test('cancel restores draft and ignores late results', async () => {
  const h = setup();
  await h.recording();
  h.sockets[0].emit({ type: 'partial', text: '取消的录音' });
  const lateCallback = h.sockets[0].onmessage;
  h.speech.cancel();
  lateCallback({ data: JSON.stringify({ type: 'final', text: '过期结果' }) });
  assert.equal(h.input.value, '已有文字');
  assert.equal(h.track.stopped, true);
  assert.equal(h.contexts[0].closed, true);
});

test('cancel while permission is pending releases a late microphone stream', async () => {
  let resolve;
  const h = setup(() => new Promise((r) => { resolve = r; }));
  const starting = h.speech.start();
  await Promise.resolve();
  h.speech.cancel();
  resolve(h.media);
  await starting;
  assert.equal(h.track.stopped, true);
  assert.equal(h.sockets.length, 0);
  assert.equal(h.speech.active.value, false);
});

test('network failure keeps transcript and releases all resources', async () => {
  const h = setup();
  await h.recording();
  h.sockets[0].emit({ type: 'partial', text: '已识别' });
  h.sockets[0].onclose();
  assert.equal(h.input.value, '已有文字 已识别');
  assert.equal(h.speech.active.value, false);
  assert.equal(h.track.stopped, true);
  assert.match(h.speech.error.value, /断开/);
});

test('permission denial displays a useful error without creating a socket', async () => {
  const h = setup(async () => { throw new DOMException('denied', 'NotAllowedError'); });
  await h.speech.start();
  assert.match(h.speech.error.value, /权限被拒绝/);
  assert.equal(h.sockets.length, 0);
  assert.equal(h.contexts[0].closed, true);
});

test('slow network stops instead of growing an unbounded audio queue', async () => {
  const h = setup();
  await h.recording();
  h.sockets[0].bufferedAmount = 64001;
  h.processors[0].emit({ type: 'audio', buffer: new ArrayBuffer(3200) });
  assert.equal(h.track.stopped, true);
  assert.equal(h.speech.active.value, false);
  assert.match(h.speech.error.value, /过慢/);
});

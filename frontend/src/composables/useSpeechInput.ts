import { computed, onBeforeUnmount, ref, type Ref } from 'vue';

type SpeechState = 'idle' | 'connecting' | 'recording' | 'finishing';

export function useSpeechInput(input: Ref<string>) {
  const state = ref<SpeechState>('idle');
  const error = ref('');
  const elapsed = ref(0);
  const notice = ref('');
  const active = computed(() => state.value !== 'idle');
  let generation = 0;
  let socket: WebSocket | null = null;
  let context: AudioContext | null = null;
  let stream: MediaStream | null = null;
  let processor: AudioWorkletNode | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let gain: GainNode | null = null;
  let timer: ReturnType<typeof setInterval> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let prefix = '';
  let transcript = '';
  let finished = false;

  const releaseAudio = () => {
    if (timer) clearInterval(timer);
    timer = undefined;
    if (processor) processor.port.onmessage = null;
    processor?.disconnect();
    source?.disconnect();
    gain?.disconnect();
    stream?.getTracks().forEach((track) => { track.onended = null; track.stop(); });
    void context?.close().catch(() => {});
    processor = null;
    source = null;
    gain = null;
    stream = null;
    context = null;
  };

  const cleanup = () => {
    generation++;
    if (deadline) clearTimeout(deadline);
    deadline = undefined;
    releaseAudio();
    if (socket) {
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      socket.close();
    }
    socket = null;
    state.value = 'idle';
  };

  const fail = (message: string) => {
    error.value = message;
    notice.value = transcript ? '已保留识别文字，请核对后发送或重新录音。' : '';
    cleanup();
  };

  const cancel = () => {
    if (!active.value) return;
    input.value = prefix;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'cancel' }));
    cleanup();
    error.value = '';
    notice.value = '已取消录音';
  };

  const finish = () => {
    if (state.value !== 'recording') return;
    state.value = 'finishing';
    notice.value = '正在确认最后一段文字…';
    // Flush on the audio thread before disconnecting; don't lose a short tail.
    processor?.port.postMessage({ type: 'finish' });
    deadline = setTimeout(() => fail('语音识别结束超时，请核对文字后重试'), 12000);
  };

  const start = async () => {
    if (active.value) return;
    error.value = '';
    notice.value = '';
    elapsed.value = 0;
    prefix = input.value;
    transcript = '';
    finished = false;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      error.value = '麦克风需要 HTTPS 或 localhost 环境，请使用安全地址打开';
      return;
    }
    if (!window.AudioContext || !window.AudioWorkletNode) {
      error.value = '当前浏览器不支持实时录音，请使用新版 Chrome、Edge 或 Safari';
      return;
    }
    state.value = 'connecting';
    notice.value = '正在连接，请允许使用麦克风…';
    const current = ++generation;
    try {
      // Resume in the click gesture; mobile browsers may otherwise suspend it.
      const audioContext = new AudioContext({ latencyHint: 'interactive' });
      context = audioContext;
      await audioContext.resume();
      if (current !== generation) return;
      const media = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (current !== generation) { media.getTracks().forEach((track) => track.stop()); return; }
      stream = media;
      stream.getTracks().forEach((track) => { track.onended = () => fail('麦克风已断开，请重新录音'); });
      const url = new URL('/api/speech/stream', window.location.href);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws = new WebSocket(url);
      socket = ws;
      const moduleReady = audioContext.audioWorklet.addModule('/audio/pcm-worklet.js');
      void moduleReady.catch(() => { if (current === generation) fail('录音组件加载失败，请刷新页面重试'); });
      deadline = setTimeout(() => fail('连接语音服务超时，请重试'), 12000);
      ws.onopen = () => ws.send(JSON.stringify({ type: 'start', format: 'pcm_s16le', sample_rate: 16000, channels: 1 }));
      ws.onerror = () => { if (current === generation) fail('无法连接语音服务，请检查网络后重试'); };
      ws.onclose = () => {
        if (current === generation && !finished) fail('语音连接已断开，请核对已识别的文字');
      };
      ws.onmessage = (event) => {
        if (current !== generation) return;
        let data: Record<string, unknown>;
        try { data = JSON.parse(event.data); }
        catch { fail('语音服务返回异常，请重新录音'); return; }
        if (data.type === 'error') {
          fail(typeof data.message === 'string' ? data.message : '语音识别失败，请重试');
        } else if (data.type === 'ready') {
          void (async () => {
            await moduleReady;
            if (current !== generation) return;
            if (deadline) clearTimeout(deadline);
            const maxSeconds = Number(data.max_duration_seconds) || 60;
            processor = new AudioWorkletNode(audioContext, 'speech-pcm', {
              numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
              processorOptions: { maxSamples: maxSeconds * 16000 },
            });
            processor.onprocessorerror = () => fail('录音处理异常，请重新录音');
            processor.port.onmessage = ({ data: packet }) => {
              if (current !== generation) return;
              if (packet.type === 'audio') {
                if (ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 64000) {
                  fail('网络发送过慢，录音已停止，请核对文字后重试');
                  return;
                }
                ws.send(packet.buffer);
              } else if (packet.type === 'flushed') {
                if (deadline) clearTimeout(deadline);
                state.value = 'finishing';
                notice.value = '正在确认最后一段文字…';
                ws.send(JSON.stringify({ type: 'finish' }));
                releaseAudio();
                deadline = setTimeout(() => fail('等待最终识别结果超时，请核对文字后重试'), 12000);
              }
            };
            source = audioContext.createMediaStreamSource(media);
            gain = audioContext.createGain();
            gain.gain.value = 0;
            source.connect(processor).connect(gain).connect(audioContext.destination);
            state.value = 'recording';
            notice.value = '正在聆听，识别文字会实时显示';
            const began = performance.now();
            timer = setInterval(() => {
              elapsed.value = Math.min(maxSeconds, Math.floor((performance.now() - began) / 1000));
              if (elapsed.value >= maxSeconds) finish();
            }, 200);
          })().catch(() => { if (current === generation) fail('无法启动录音，请重新尝试'); });
        } else if (data.type === 'partial' || data.type === 'final') {
          if (typeof data.text === 'string') {
            transcript = data.text;
            input.value = prefix + (prefix && transcript && !/\s$/.test(prefix) ? ' ' : '') + transcript;
          }
          if (data.type === 'final') {
            finished = true;
            cleanup();
            notice.value = transcript.trim() ? '识别完成，可修改文字后点击发送' : '没有识别到说话声，请重新录音';
          }
        }
      };
    } catch (cause) {
      if (current !== generation) return;
      const name = cause instanceof DOMException ? cause.name : '';
      fail(name === 'NotAllowedError' ? '麦克风权限被拒绝，请在浏览器设置中允许后重试'
        : name === 'NotFoundError' ? '未找到可用麦克风，请连接设备后重试'
          : '无法启动麦克风，请检查设备是否被其他程序占用');
    }
  };

  onBeforeUnmount(cleanup);
  return { state, active, elapsed, error, notice, start, finish, cancel };
}

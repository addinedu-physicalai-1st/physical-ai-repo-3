// 마이크 PCM 을 1280 샘플 (80ms @ 16kHz) 청크로 메인 쓰레드에 전달.
// AudioContext 가 16kHz 로 생성됐다는 전제 (브라우저가 자동 리샘플링).
// 출력 형식: Int16Array (openwakeword 입력 스케일에 맞춤).
class PCMCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.CHUNK = 1280;
    this.buf = new Float32Array(this.CHUNK);
    this.fill = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;

    let i = 0;
    while (i < ch.length) {
      const need = this.CHUNK - this.fill;
      const take = Math.min(need, ch.length - i);
      this.buf.set(ch.subarray(i, i + take), this.fill);
      this.fill += take;
      i += take;

      if (this.fill === this.CHUNK) {
        const out = new Int16Array(this.CHUNK);
        for (let j = 0; j < this.CHUNK; j++) {
          const s = Math.max(-1, Math.min(1, this.buf[j]));
          out[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        this.port.postMessage(out, [out.buffer]);
        this.fill = 0;
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PCMCapture);

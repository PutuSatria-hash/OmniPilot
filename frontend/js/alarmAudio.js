/**
 * Lightweight Web Audio API alarm siren for browser/PWA critical alerts.
 */
class AlarmAudioController {
  constructor() {
    this._ctx = null;
    this._interval = null;
  }

  start() {
    if (this._interval) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this._ctx = new AudioCtx();
      const pulse = () => {
        if (!this._ctx) return;
        const osc = this._ctx.createOscillator();
        const gain = this._ctx.createGain();
        osc.type = "triangle";
        osc.frequency.setValueAtTime(880, this._ctx.currentTime);
        osc.frequency.setValueAtTime(1320, this._ctx.currentTime + 0.18);
        gain.gain.setValueAtTime(0.22, this._ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, this._ctx.currentTime + 0.42);
        osc.connect(gain);
        gain.connect(this._ctx.destination);
        osc.start();
        osc.stop(this._ctx.currentTime + 0.44);
      };
      pulse();
      this._interval = setInterval(pulse, 1200);
    } catch {
      // Browser autoplay policy may block audio until user gesture
    }
  }

  stop() {
    if (this._interval) {
      clearInterval(this._interval);
      this._interval = null;
    }
    if (this._ctx) {
      this._ctx.close().catch(() => {});
      this._ctx = null;
    }
  }
}

export const alarmAudio = new AlarmAudioController();

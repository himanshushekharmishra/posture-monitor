// Sound cues on the slouch meter (Web Audio).
//   When slouching starts, the sound for the meter range the score is in plays.
//   Slumping into a higher range during the same slouch plays that range's sound;
//   the same or a lower range never plays again in that slouch. An alert and
//   sitting back up have their own sounds. Each sound is levelled to the same
//   loudness and its silent ending trimmed. The files live in frontend/sounds/
//   (see the README there); a missing file is skipped, not an error.

const QUIET_DB = -40; // windows quieter than this count as silence
const WINDOW_SECONDS = 0.05;
const TAIL_SECONDS = 0.1; // kept after the last sounding window
const MAX_PEAK = 0.89; // -1 dBFS: levelling never pushes a sound into clipping

const SLOUCHING = new Set(["slouching", "alerted"]);

/**
 * Which sound one frame should trigger. Pure, so it can be tested.
 * `bands` are [{from, file}] in rising order; `from` is the score as a multiple of the
 * slouch threshold (1 = the alert line on the meter). `band` is the highest range
 * already played in the current slouch (-1 for none). Returns [sound key | null, band].
 */
export function soundFor(msg, threshold, bands, band) {
  if (msg.event === "slouch_started") band = -1; // a new slouch starts from the bottom
  let key = null;
  if (SLOUCHING.has(msg.state) && msg.score !== null) {
    const ratio = msg.score / threshold;
    let current = -1;
    bands.forEach((b, i) => {
      if (ratio >= b.from) current = i;
    });
    if (current > band) {
      key = `band${current}`;
      band = current;
    }
  } else if (!SLOUCHING.has(msg.state)) {
    band = -1;
  }
  if (msg.event === "alerted") key = "alert"; // these win over a range sound
  if (msg.event === "recovered") key = "recovered";
  return [key, band];
}

/**
 * Gain that brings a sound's sounding part to `targetDb`, and where its sound ends.
 * `channels` are Float32Arrays of samples. Pure, so it can be tested.
 */
export function levelling(channels, sampleRate, targetDb) {
  const n = channels[0].length;
  const win = Math.max(1, Math.round(sampleRate * WINDOW_SECONDS));
  const quiet = 10 ** (QUIET_DB / 20);
  let peak = 0;
  let loudSum = 0;
  let loudWindows = 0;
  let lastLoud = -1;
  for (let w = 0; w * win < n; w++) {
    let sum = 0;
    const end = Math.min(n, (w + 1) * win);
    for (let i = w * win; i < end; i++) {
      let v = 0;
      for (const c of channels) {
        v += c[i];
        peak = Math.max(peak, Math.abs(c[i])); // per channel: a mono mix hides stereo peaks
      }
      v /= channels.length;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / (end - w * win));
    if (rms > quiet) {
      loudSum += rms * rms;
      loudWindows++;
      lastLoud = w;
    }
  }
  if (!loudWindows) return { gain: 0, end: 0 }; // silent file
  const loudness = Math.sqrt(loudSum / loudWindows);
  const gain = Math.min(10 ** (targetDb / 20) / loudness, MAX_PEAK / peak);
  const end = Math.min(n / sampleRate, (lastLoud + 1) * WINDOW_SECONDS + TAIL_SECONDS);
  return { gain, end };
}

/** The player. Browsers only allow audio after a click, so call unlock() from one. */
export function createSoundPlayer() {
  let ctx = null;
  let loading = null;
  const sounds = new Map(); // key -> {buffer, gain, end}
  let current = null;
  let enabled = true;

  async function loadOne(key, file, targetDb) {
    try {
      const res = await fetch(`/sounds/${encodeURIComponent(file)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buffer = await ctx.decodeAudioData(await res.arrayBuffer());
      const channels = [...Array(buffer.numberOfChannels).keys()].map((c) => buffer.getChannelData(c));
      sounds.set(key, { buffer, ...levelling(channels, buffer.sampleRate, targetDb) });
    } catch (err) {
      console.warn(`Sound ${file} not available:`, err.message);
    }
  }

  function loadAll(config) {
    const files = config.web_sound_bands.map((b, i) => [`band${i}`, b.file]);
    files.push(["alert", config.web_sound_alert], ["recovered", config.web_sound_recovered]);
    return Promise.all(files.filter(([, file]) => file)
      .map(([key, file]) => loadOne(key, file, config.web_sound_loudness_db)));
  }

  return {
    /** Start audio (needs a click) and load the sounds the first time. */
    unlock(config) {
      if (!ctx) ctx = new AudioContext();
      ctx.resume();
      loading ??= loadAll(config);
    },
    get enabled() {
      return enabled;
    },
    set enabled(on) {
      enabled = on;
      if (!on) current?.stop();
    },
    /** Play a sound by key, cutting off one that's still playing. */
    play(key) {
      const s = enabled && ctx && sounds.get(key);
      if (!s || !s.gain) return;
      current?.stop();
      const source = ctx.createBufferSource();
      source.buffer = s.buffer;
      const gain = ctx.createGain();
      gain.gain.value = s.gain;
      source.connect(gain).connect(ctx.destination);
      source.start(0, 0, s.end);
      current = source;
      source.onended = () => {
        if (current === source) current = null;
      };
    },
  };
}

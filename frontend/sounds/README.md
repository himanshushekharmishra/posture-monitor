# Sound cues

The web page plays these while you slouch (see `web_sound_*` in `config/settings.json`).
The clips aren't in git: they're third-party meme sounds, so add your own copies here.
A missing file is skipped; the page stays silent for that cue.

| File | Plays |
|---|---|
| `wrong-answer.mp3` | slouching starts, score 1-1.25x the threshold (just past the alert line) |
| `oh-my-god.mp3` | score 1.25-1.5x |
| `wake-up-to-reality.mp3` | score 1.5-1.75x |
| `metal-pipe-clang.mp3` | score 1.75-2x |
| `chicken-screaming.mp3` | score 2x or more (meter full) |
| `metal-gear-alert.mp3` | the alert fires |
| `kids-yay.mp3` | you sit back up after slouching |

Any MP3, OGG or WAV works; change the names or ranges in `config/settings.json`.
Sounds are levelled to `web_sound_loudness_db` and their silent endings trimmed.

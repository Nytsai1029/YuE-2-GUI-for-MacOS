# YuE Studio

A quality harness and studio UI for **YuE2** song generation on Apple Silicon (via
[mlx-Yue](https://github.com/vanch007/mlx-Yue)). You write the lyrics and pick the sound;
YuE Studio catches the avoidable problems before, during and after generation:

- lyrics lost, jumbled or sections sung 2–3×
- melodies that loop, chords that are too simple
- crammed or rushed syllables, strained range, humming instead of words
- shouted and rushed line endings with frantic fills, abrupt endings, clipping

It uses YuE2's **score-first** design. The model writes an ABC score, which is checked
and repaired (reharmonise, transpose, tempo, fix sections) *before* any audio is rendered.
Takes are then gated, compared and finalised at full quality. Every check lives in one
catalog (open **Checks** in the app); new failure modes your team marks in Review can
be added over time.

It never installs or downloads YuE2: it drives **your existing mlx-Yue install** in its
own virtualenv, as a supervised subprocess.

## Install (on the Mac that runs mlx-Yue)

```bash
cd YuE-Studio
python3 -m venv .venv
.venv/bin/pip install -e .
# optional: lyric checking by speech recognition (pulls mlx-whisper + torch)
.venv/bin/pip install -e ".[asr]"
```

The web UI is pre-built into `yuestudio/static/app`. To change the UI you need Node:
`cd web && npm install && npm run build`.

## First run: probe your engine

```bash
.venv/bin/yue-studio probe --mlx-yue ~/mlx-Yue \
    --model ~/mlx-Yue/models/converted --vae /path/to/YuE2-Vae --precision bf16
```

The probe loads the model, writes a score, generates tokens, renders at 8 and 32 steps,
tests cancel, determinism and every ABC edit, and records calibration (speed, ABC tokens
per bar). It writes a JSON report under `~/Library/Application Support/YuE Studio/probe/`.
Send that report back if anything fails.

## Run

```bash
.venv/bin/yue-studio            # serve on http://localhost:8765 and open the browser
.venv/bin/yue-studio serve --host 0.0.0.0   # team access on the LAN (set a token in Settings)
.venv/bin/yue-studio serve --fake --open    # built-in fake engine, no model needed
.venv/bin/yue-studio smoke      # one Draft song end to end from the terminal
.venv/bin/yue-studio doctor     # show what was auto-detected
```

In the app: **Settings → Engine**. Choose your mlx-Yue folder (**Detect** finds its
`.venv`, model and VAE), then **Load engine**.

## Workflow

1. **Write**: the lyrics editor shows section colours, syllables per line and live checks
   with one-click fixes. The Style builder has presets (including **Instrumental (no
   lyrics)** and EDM styles such as artcore and hardcore) and shows what the singer and
   the model receive.
2. **Generate**:
   - **Draft**: 1 score, 1 take, preview quality.
   - **Standard**: up to 3 scores and 2 takes, checked, ranked and finalised.
   - **Best**: up to 6 scores and 4 takes.
3. **Plan**: every score gets a scorecard (Lyrics / Singing / Variety / Harmony), an
   engraved lead sheet with your lyrics under the notes, an instant sketch player, and
   repairs.
4. **Review**: A/B the takes on the waveform with section bands and markers for detected
   problems. You can **mark an issue** on any range, then Finalize, Re-roll (composition /
   performance / texture) or Export. Exports: mastered FLAC, MP3, LRC, ABC, MIDI, plus a
   recipe JSON for exact replay.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # 69 tests, fake engine with fault injection
.venv/bin/ruff check yuestudio yuestudio_worker tests fake_lyra
```

`fake_lyra/` mimics mlx-Yue's API and emits real dialect ABC. It injects failures via
`YUESTUDIO_FAKE_FAULTS` (for example `repeat_section,cram:0.5,leap_end,busy_ins,sem_loop,shout,hum`),
so every detector can be exercised without the model.

Layout:
- `yuestudio_worker/`: runs inside the user's mlx-Yue venv (stdlib + numpy + soundfile)
- `yuestudio/`: server (FastAPI), with these modules:
  - lyrics / style lint
  - ABC model and edits
  - analysis
  - repair
  - director
  - jobs
  - audio
  - ASR alignment
- `web/`: React UI

## Licensing

- YuE Studio's own code is yours.
- `yuestudio/abc/_vendor/abc_tools.py` is from mlx-Yue (Apache-2.0, see the LICENSE next to it).
- YuE2 model weights are CC BY-NC 4.0 with a creator permission: you may monetise songs
  you create. Selling or hosting the software commercially needs a licence from HKGAI.
- Exports carry AI-generation disclosure metadata.

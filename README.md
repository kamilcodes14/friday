# F.R.I.D.A.Y.

A personal AI voice assistant modeled after the Iron Man AI — two versions in this repo:

| File | What it is |
|---|---|
| `friday_core.py` + `friday_gui.py` | Desktop version. Python + Tkinter HUD, real double-clap wake detection, mic input, system TTS, Claude as the brain. |
| `friday.html` | Browser version. Single-file HTML/CSS/JS port with an animated canvas HUD, Web Speech API for voice in/out, and a typed-text fallback. |

Built by Syed — CS student at UMT Lahore.

## Features
- Wake on command (clap detection in the desktop app, a WAKE button / double-click in the browser app)
- Natural conversation powered by Claude
- Mock interview coach — generates role-specific questions, asks them one at a time, gives feedback at the end
- Local commands (time, date, clear memory, sleep/standby)

## Running the desktop version

```bash
pip install -r requirements.txt
```

Set your Anthropic API key as an environment variable before running:

```bash
export ANTHROPIC_API_KEY="your-key-here"   # Windows: setx ANTHROPIC_API_KEY "your-key-here"
python friday_gui.py        # GUI with the HUD
python friday_core.py       # console-only mode
```

Notes:
- `pyaudio` needs PortAudio installed on your system (`brew install portaudio` on macOS, `apt install portaudio19-dev` on Linux) before `pip install` will succeed.
- Double-clap detection is tuned by `CLAP_THRESHOLD` in `friday_core.py` — adjust it to your mic's sensitivity.

## Running the browser version

`friday.html` is a self-contained file — no build step, no dependencies.

**Heads up on the API call:** the file calls `https://api.anthropic.com/v1/messages` directly from the browser with no API key baked in. That's intentional for running it inside a Claude.ai artifact (the key is injected for you there). If you open `friday.html` on its own — locally or via GitHub Pages — those calls will fail, since there's no key attached and the Anthropic API doesn't allow bare browser calls.

To make it work standalone, you'd need to:
1. Add your key to the request headers along with the `anthropic-dangerous-direct-browser-access: true` header.
2. **Not** commit that key to a public repo — anyone who views the page source can read it. For a public-facing standalone version, route the API call through your own small backend instead, and keep the key server-side.

Voice input uses the Web Speech API (Chrome/Edge only). Other browsers fall back to the text box automatically.

## License
Personal project — no license specified yet.

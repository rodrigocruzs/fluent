# Fluent

Mac menu bar app that passively records meetings and generates a post-meeting English coaching report.

## Install

### 1. BlackHole (system audio capture)

```bash
brew install blackhole-2ch
```

Then in **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup"):
1. Click `+` → **Create Multi-Output Device**
2. Add: `BlackHole 2ch` + your speakers/headphones
3. Set this Multi-Output Device as your **system output** in System Settings → Sound
4. Set **BlackHole 2ch** as your **input** in System Settings → Sound (or Fluent does it automatically)

### 2. Python dependencies

```bash
brew install portaudio
pip install -r requirements.txt
```

For pyannote.audio you also need a Hugging Face token with access to
`pyannote/speaker-diarization-3.1` (free, just accept the model terms):

```bash
export HF_TOKEN=hf_your_token_here
```

### 3. Configure

```bash
python setup_config.py
```

Or edit `~/.fluent/config.json` directly:

```json
{
  "native_language": "Spanish",
  "job_context": "Senior product manager at a fintech company",
  "whisper_api_key": "sk-...",
  "claude_api_key": "sk-ant-..."
}
```

### 4. Test audio capture first

```bash
python test_audio.py
```

Speak + play audio for 10s, then open the resulting WAV in QuickTime to confirm both streams mixed.

### 5. Run

```bash
python app.py
```

A 🎙 icon appears in the menu bar. Click it to **Start session** before your meeting.

## First run — speaker selection

After your first session, Fluent will ask *"Which speaker are you?"* — diarisation discovers all voices in the room and needs to know which label is yours. Enter the number and click **Save & reprocess**. Fluent remembers it for all future sessions.

## Report location

Reports are saved to `~/.fluent/reports/` and open automatically in your browser after each session.

## Project layout

```
fluent/
  audio.py       — mic + BlackHole capture
  transcribe.py  — Whisper API
  diarise.py     — pyannote speaker diarisation
  coach.py       — Claude coaching prompt
  pipeline.py    — orchestrates the above
  report.py      — HTML report generator
  config.py      — ~/.fluent/config.json
app.py           — rumps menu bar app
test_audio.py    — standalone audio test
setup_config.py  — first-run config wizard
```

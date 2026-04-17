# Plan: Make `make_tutorial('hooks for harness engineering')` Actually Run

## Problem
The 7-stage pipeline code is well-structured but cannot execute end-to-end because:
1. No pre-flight validation — missing env vars/tools cause cryptic mid-pipeline crashes
2. No Azure credentials configured (`AZURE_OPENAI_ENDPOINT`, `AZURE_SPEECH_REGION`)
3. ffmpeg/ffprobe not installed (required by TTS, recording, editing, video validation)
4. Playwright browsers not installed (required by recording stage)
5. Several stages crash ungracefully when external tools are missing

## Approach
Three phases: harden code → configure environment → execute pipeline.

### Phase 1: Code hardening (parallel)
- **preflight-check**: Add `src/preflight.py` with validation of env vars, tools, and deps before pipeline starts. Wire into `make_tutorial()` as Stage -1.
- **graceful-recording**: Add "placeholder" recording mode that generates a blank video when no recording tools are available, so the pipeline can still produce voice + script output.
- **fix-video-validation**: Make `validate_video` skip gracefully when ffprobe isn't available (log warning, don't crash).
- **fix-tts-fallback**: Ensure TTS stage degrades gracefully: Azure Speech → OpenAI TTS → error with clear message.

### Phase 2: Environment setup (sequential)
- **install-ffmpeg**: Install ffmpeg via winget/choco.
- **configure-azure**: Login to Azure, discover/set OpenAI endpoint, configure env vars.
- **install-playwright**: Install Playwright Chromium browser.

### Phase 3: Execute & critique (sequential)
- **run-pipeline**: Execute `make_tutorial('hooks for harness engineering')`.
- **critique**: Review all outputs and critique the work.

## Todos
1. `preflight-check` — Add src/preflight.py, wire into make_tutorial
2. `graceful-recording` — Add placeholder recording mode for missing tools
3. `fix-video-validation` — Skip ffprobe validation gracefully when unavailable
4. `fix-tts-fallback` — Better error messages when both TTS providers fail
5. `install-ffmpeg` — Install ffmpeg via package manager
6. `configure-azure` — Set up Azure OpenAI credentials and env vars
7. `install-playwright` — Install Playwright Chromium
8. `run-pipeline` — Execute make_tutorial('hooks for harness engineering')
9. `critique-work` — Review outputs and self-critique

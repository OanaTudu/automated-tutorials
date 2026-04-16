---
title: Tutorial Factory Pipeline
description: Automated pipeline that generates narrated tutorial videos from a single function call
ms.date: 2026-04-06
---

## Overview

This project provides a `make_tutorial("topic")` function that orchestrates five pipeline stages to produce
curated tutorial videos under 5 minutes. Each stage runs independently with shared Pydantic data contracts
and a YAML-driven configuration layer.

## Quickstart

```bash
# Install dependencies
uv sync

# Run the pipeline (once all stages are implemented)
uv run python -m src.make_tutorial "Getting started with Python virtual environments"
```

## Pipeline Stages

1. **Script generation** generates a structured narration script using an LLM with schema-enforced output.
2. **Voice synthesis** converts the script narration to audio using Azure AI Speech or OpenAI TTS.
3. **Screen recording** captures a browser or desktop demo aligned with the shot list.
4. **Post-production** composites voice, video, and optional captions using ffmpeg.
5. **Publishing** saves the finished tutorial to the output folder.

## Project Structure

```text
tutorials/
  config/pipeline.yaml    # Provider settings, voices, export profiles
  prompts/                 # Jinja2 prompt templates for script generation
  src/                     # Pipeline stage modules and shared models
  tests/                   # Unit and integration tests
  outputs/                 # Generated tutorial artifacts
```

## Configuration

All provider settings, voice names, export profiles, and output paths live in
[config/pipeline.yaml](config/pipeline.yaml). Swap providers or adjust quality settings without changing code.

Key configuration sections:

- `pipeline`: global settings (max duration, output root, log level)
- `script`: LLM provider, model, temperature, token limits
- `tts`: primary and fallback voice synthesis providers with voice settings
- `recording`: screen capture mode (Playwright, OBS, or ffmpeg)
- `post`: ffmpeg export settings and caption engine configuration

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/
```

## Architecture

Each pipeline stage receives a `TutorialScript` (or prior stage output) and returns a `StageResult`.
Stages communicate through typed Pydantic models defined in `src/models.py`, ensuring each stage
can be developed, tested, and swapped independently.

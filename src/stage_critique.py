"""Self-critique stage — evaluates the generated tutorial script for quality."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import (
    CritiqueResult,
    CritiqueScores,
    ResearchResult,
    StageResult,
    TutorialScript,
)
from .stage_script import _create_client

logger = logging.getLogger(__name__)

_CRITIQUE_SYSTEM = (
    "You are a senior instructional-design reviewer. "
    "Given a tutorial script and the original research material, "
    "evaluate the script on five dimensions (each scored 1-10) and "
    "return structured JSON matching the requested schema."
)


def _build_critique_prompt(
    script: TutorialScript,
    research: ResearchResult,
    audience: str,
) -> str:
    """Build the user prompt that asks the LLM to critique the tutorial."""
    sections_text = "\n".join(
        f"  {i + 1}. {s.title} ({s.target_seconds}s) — "
        f"{len(s.key_points)} key points"
        for i, s in enumerate(script.sections)
    )
    return f"""\
Evaluate the following tutorial script against the research material below.

## Research material
- **Topic**: {research.topic}
- **Key findings**: {json.dumps(research.key_findings, indent=2)}
- **Sources**: {json.dumps(research.sources, indent=2)}
- **Code examples provided**: {len(research.code_examples)}

## Tutorial script
- **Topic**: {script.topic}
- **Target audience**: {audience}
- **Target duration**: {script.total_target_seconds}s (~{script.estimated_words} words)
- **Hook**: {script.hook}
- **Sections** ({len(script.sections)}):
{sections_text}
- **Recap**: {script.recap}
- **CTA**: {script.cta}

## Scoring criteria (1-10 each)
1. **accuracy** — Are the facts in the script consistent with the research findings?
2. **completeness** — Does the script cover the key findings from research?
3. **pacing** — Is the narration density appropriate for the target duration?
4. **audience_fit** — Is the content appropriate for the target audience ({audience})?
5. **teaching_effectiveness** — Does the script follow good pedagogy (hook, examples, recap)?

Compute **overall_grade** as the weighted mean:
  accuracy×0.25 + completeness×0.20 + pacing×0.15 + audience_fit×0.20 + teaching_effectiveness×0.20

List concrete **strengths** and actionable **improvements**.
Return ONLY the JSON object matching the schema."""


def _default_critique(reason: str) -> CritiqueResult:
    """Return a safe default critique when the LLM call fails."""
    return CritiqueResult(
        scores=CritiqueScores(
            accuracy=5.0,
            completeness=5.0,
            pacing=5.0,
            audience_fit=5.0,
            teaching_effectiveness=5.0,
        ),
        overall_grade=5.0,
        strengths=[],
        improvements=[],
        summary=f"Critique could not be completed: {reason}",
    )


def critique_tutorial(
    script: TutorialScript,
    research: ResearchResult,
    output_dir: Path,
    config: dict,
    audience: str = "data scientists",
) -> StageResult:
    """Critique the generated tutorial script using an LLM.

    Sends the script and research context to the configured LLM, asks for a
    structured ``CritiqueResult``, and persists the evaluation as
    ``critique.json`` in *output_dir*.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    user_prompt = _build_critique_prompt(script, research, audience)
    input_messages: list[dict[str, str]] = [
        {"role": "user", "content": user_prompt},
    ]

    try:
        client = _create_client(config)
        provider = config["script"].get("provider", "openai")
        model = config["script"]["model"]
        max_tokens = config["script"]["max_output_tokens"]

        if provider == "azure_openai":
            messages = [
                {"role": "system", "content": _CRITIQUE_SYSTEM},
                *input_messages,
            ]
            resp = client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=CritiqueResult,
                max_completion_tokens=max_tokens,
            )
            critique = resp.choices[0].message.parsed
        else:
            resp = client.responses.parse(
                model=model,
                instructions=_CRITIQUE_SYSTEM,
                input=input_messages,
                text_format=CritiqueResult,
                max_output_tokens=max_tokens,
            )
            critique = resp.output_parsed

        logger.info(
            "Critique completed — overall grade: %.1f", critique.overall_grade,
        )

    except Exception as exc:
        logger.warning("Critique stage failed, using defaults: %s", exc)
        critique = _default_critique(str(exc))

    critique_path = output_dir / "critique.json"
    critique_path.write_text(
        critique.model_dump_json(indent=2), encoding="utf-8",
    )

    return StageResult(
        stage="critique",
        success=True,
        output_path=str(critique_path),
        metadata={"overall_grade": critique.overall_grade},
    )

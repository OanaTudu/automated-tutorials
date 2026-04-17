"""Script generation stage using OpenAI Responses API with structured outputs."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from openai import OpenAI

from .models import StageResult, TutorialScript
from .quality_gates import validate_script

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_MAX_ATTEMPTS = 3


def _create_client(config: dict) -> OpenAI:
    """Create the appropriate OpenAI client based on provider config."""
    provider = config["script"].get("provider", "openai")
    if provider == "azure_openai":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(
                exclude_interactive_browser_credential=False,
            ),
            "https://cognitiveservices.azure.com/.default",
        )
        azure_cfg = config["script"].get("azure_openai", {})
        return AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version=azure_cfg.get("api_version", "2025-04-01-preview"),
        )
    return OpenAI()


def generate_script(
    topic: str,
    output_dir: Path,
    config: dict,
) -> StageResult:
    """Generate a tutorial script using LLM with structured output.

    Renders Jinja2 prompt templates, calls the OpenAI Responses API with
    ``text_format=TutorialScript`` for schema-enforced output, and runs
    quality-gate validation with a single repair retry on failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. Render prompts from Jinja2 templates --------------------------
    env = Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        autoescape=False,
    )
    system_prompt = env.get_template("tutorial_system.jinja2").render(
        audience=config.get("audience", "beginner developers"),
        max_duration_seconds=config["pipeline"]["max_duration_seconds"],
    )
    user_prompt = env.get_template("tutorial_user.jinja2").render(
        topic=topic,
        audience=config.get("audience", "beginner developers"),
        target_seconds=config["pipeline"]["max_duration_seconds"],
        source_material=config.get("source_material", ""),
    )

    # Append revision feedback from critique retry when present
    revision_feedback = config.get("revision_feedback", "")
    if revision_feedback:
        user_prompt += (
            f"\n\nREVISION FEEDBACK from quality review:\n{revision_feedback}\n"
            "Address each point in the revised script."
        )

    # --- 2. Call LLM with retry/repair loop --------------------------------
    client = _create_client(config)
    provider = config["script"].get("provider", "openai")
    script: TutorialScript | None = None
    last_error: str | None = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            input_messages: list[dict[str, str]] = [
                {"role": "user", "content": user_prompt},
            ]
            if last_error:
                input_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Previous output failed validation: {last_error}. "
                            "Fix the issues and return valid JSON."
                        ),
                    },
                )

            parsed = _call_structured(
                client, config, system_prompt, input_messages, provider,
            )

            # Run quality-gate validation before accepting the script
            max_seconds = config["pipeline"]["max_duration_seconds"]
            errors = validate_script(parsed, max_seconds=max_seconds)
            if errors:
                last_error = "; ".join(errors)
                logger.warning(
                    "Quality gate failed on attempt %d: %s",
                    attempt + 1,
                    last_error,
                )
                continue

            script = parsed
            logger.info("Script generated successfully on attempt %d", attempt + 1)
            break

        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "Script generation attempt %d failed: %s",
                attempt + 1,
                exc,
            )

    if script is None:
        raise RuntimeError(f"Script generation failed after {_MAX_ATTEMPTS} attempts: {last_error}")

    # --- 3. Persist outputs -----------------------------------------------
    script_path = output_dir / "script.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")

    return StageResult(
        stage="script",
        success=True,
        output_path=str(script_path),
        metadata={
            "words": script.estimated_words,
            "sections": len(script.sections),
        },
    )


def _call_structured(
    client: OpenAI,
    config: dict,
    system_prompt: str,
    input_messages: list[dict[str, str]],
    provider: str,
) -> TutorialScript:
    """Call the LLM for structured TutorialScript output."""
    model = config["script"]["model"]
    max_tokens = config["script"]["max_output_tokens"]

    if provider == "azure_openai":
        messages = [{"role": "system", "content": system_prompt}, *input_messages]
        resp = client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=TutorialScript,
            max_completion_tokens=max_tokens,
        )
        return resp.choices[0].message.parsed

    resp = client.responses.parse(
        model=model,
        instructions=system_prompt,
        input=input_messages,
        text_format=TutorialScript,
        max_output_tokens=max_tokens,
    )
    return resp.output_parsed

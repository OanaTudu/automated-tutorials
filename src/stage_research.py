"""Research stage — gathers source material before script generation."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from openai import OpenAI

from .models import ResearchResult, StageResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior technical researcher preparing material for a tutorial video.
Your audience is {audience}.

For the given topic, produce a JSON object with these fields:
- "topic": the research topic (string)
- "sources": up to {max_sources} URLs or reference titles (list of strings)
- "key_findings": bullet-point facts covering key concepts, best practices, \
common pitfalls, and relevant datasets (list of strings)
- "code_examples": runnable code snippets that illustrate the topic (list of strings)
- "raw_notes": free-form research notes with additional context (string)

Return ONLY valid JSON — no markdown fences, no commentary outside the object.
"""


def _get_research_config(config: dict) -> dict:
    """Return the research config, falling back to script config for provider settings."""
    research = config.get("research", {})
    script = config.get("script", {})
    return {
        "provider": research.get("provider", script.get("provider", "openai")),
        "model": research.get("model", script.get("model", "gpt-4.1")),
        "max_output_tokens": research.get(
            "max_output_tokens", script.get("max_output_tokens", 3000),
        ),
        "max_sources": research.get("max_sources", 10),
        "azure_openai": research.get("azure_openai", script.get("azure_openai", {})),
    }


def _create_client(config: dict) -> OpenAI:
    """Create the appropriate OpenAI client based on provider config."""
    research_cfg = _get_research_config(config)
    provider = research_cfg["provider"]

    if provider == "azure_openai":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(
                exclude_interactive_browser_credential=False,
            ),
            "https://cognitiveservices.azure.com/.default",
        )
        azure_cfg = research_cfg.get("azure_openai", {})
        return AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version=azure_cfg.get("api_version", "2025-04-01-preview"),
        )
    return OpenAI()


def _parse_research(raw: str, topic: str) -> ResearchResult:
    """Parse LLM text into a ResearchResult, tolerating minor formatting issues."""
    text = raw.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]

    try:
        data = json.loads(text)
        data.setdefault("topic", topic)
        return ResearchResult.model_validate(data)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Could not parse structured research output: %s", exc)
        return ResearchResult(topic=topic, raw_notes=raw)


def _research_openai(
    client: OpenAI,
    research_cfg: dict,
    system_prompt: str,
    topic: str,
) -> ResearchResult:
    """Call OpenAI Responses API with web search tool."""
    resp = client.responses.create(
        model=research_cfg["model"],
        instructions=system_prompt,
        input=[{"role": "user", "content": f"Research the following topic thoroughly: {topic}"}],
        tools=[{"type": "web_search_preview"}],
        max_output_tokens=research_cfg["max_output_tokens"],
    )
    raw_text = resp.output_text
    return _parse_research(raw_text, topic)


def _research_azure(
    client: OpenAI,
    research_cfg: dict,
    system_prompt: str,
    topic: str,
) -> ResearchResult:
    """Call Azure OpenAI Chat Completions API (no web search tool)."""
    resp = client.chat.completions.create(
        model=research_cfg["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Research the following topic thoroughly: {topic}"},
        ],
        max_completion_tokens=research_cfg["max_output_tokens"],
    )
    raw_text = resp.choices[0].message.content or ""
    return _parse_research(raw_text, topic)


def research_topic(
    topic: str,
    output_dir: Path,
    config: dict,
    audience: str = "data scientists",
) -> StageResult:
    """Research a topic and persist findings for downstream script generation.

    Uses the OpenAI Responses API with ``web_search_preview`` for the OpenAI
    provider, or Azure OpenAI Chat Completions (LLM knowledge only) for
    the Azure provider.  Results are saved as ``research.json``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    research_cfg = _get_research_config(config)

    system_prompt = _SYSTEM_PROMPT.format(
        audience=audience,
        max_sources=research_cfg["max_sources"],
    )

    logger.info("Starting research for topic: %s (provider=%s)", topic, research_cfg["provider"])

    try:
        client = _create_client(config)

        if research_cfg["provider"] == "azure_openai":
            result = _research_azure(client, research_cfg, system_prompt, topic)
        else:
            result = _research_openai(client, research_cfg, system_prompt, topic)

        logger.info(
            "Research complete — %d sources, %d findings, %d code examples",
            len(result.sources),
            len(result.key_findings),
            len(result.code_examples),
        )
    except Exception as exc:
        logger.error("Research stage failed: %s", exc)
        result = ResearchResult(topic=topic)

    research_path = output_dir / "research.json"
    research_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    return StageResult(
        stage="research",
        success=bool(result.key_findings),
        output_path=str(research_path),
        metadata={
            "source_count": len(result.sources),
            "finding_count": len(result.key_findings),
        },
    )

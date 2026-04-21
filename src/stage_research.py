"""Research stage — gathers source material before script generation."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from .models import ResearchResult, StageResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior technical researcher preparing material for a tutorial video.
Your audience is {audience}.

Domain context — AI-native development:
When the topic involves acronyms, extension names, or tool names that could be
ambiguous, always prefer the AI-native software development interpretation.
For example, "HVE" means "HyperVelocity Engineering" (a VS Code extension for
AI-native dev), not "High Variance Estimator" from statistics.  Prioritise
VS Code extensions, GitHub Copilot ecosystem tools, AI coding agents, and
modern developer-experience tooling when interpreting topics.

For the given topic, produce a JSON object with these fields:
- "topic": the research topic (string)
- "sources": up to {max_sources} URLs or reference titles (list of strings)
- "key_findings": bullet-point facts covering key concepts, best practices, \
common pitfalls, and relevant datasets (list of strings)
- "code_examples": runnable code snippets that illustrate the topic (list of strings)
- "raw_notes": free-form research notes with additional context (string)

Return ONLY valid JSON — no markdown fences, no commentary outside the object.
"""


_SUBAGENT_HEADER = """\
You are a senior technical researcher preparing material for a tutorial video.
Your audience is {audience}.

Domain context — AI-native development:
When the topic involves acronyms, extension names, or tool names that could be
ambiguous, always prefer the AI-native software development interpretation.
For example, "HVE" means "HyperVelocity Engineering" (a VS Code extension for
AI-native dev), not "High Variance Estimator" from statistics.  Prioritise
VS Code extensions, GitHub Copilot ecosystem tools, AI coding agents, and
modern developer-experience tooling when interpreting topics.
"""

_SUBAGENT_SCHEMA_FOOTER = """\
Return a JSON object with these fields:
- "topic": the research topic (string)
- "sources": up to {max_sources} URLs or reference titles (list of strings)
- "key_findings": bullet-point facts (list of strings)
- "code_examples": runnable code snippets (list of strings)
- "raw_notes": free-form research notes (string)

Return ONLY valid JSON — no markdown fences, no commentary outside the object.
"""

_SUBAGENT_PROMPTS: dict[str, str] = {
    "concepts_and_prereqs": (
        _SUBAGENT_HEADER
        + "\nFocus exclusively on core concepts and prerequisites for this subtask.\n"
        "Populate `key_findings` richly with definitions, mental models, and prerequisites; "
        "keep `code_examples` minimal (only tiny setup snippets if essential). "
        "All fields below must still be present so downstream merging is uniform.\n\n"
        + _SUBAGENT_SCHEMA_FOOTER
    ),
    "code_examples": (
        _SUBAGENT_HEADER
        + "\nFocus exclusively on runnable code examples for this subtask.\n"
        "Populate `code_examples` richly with complete, self-contained, runnable snippets "
        "that illustrate the topic; keep `key_findings` minimal (only brief captions tying "
        "each snippet to its purpose). All fields below must still be present so downstream "
        "merging is uniform.\n\n"
        + _SUBAGENT_SCHEMA_FOOTER
    ),
    "common_pitfalls": (
        _SUBAGENT_HEADER
        + "\nFocus exclusively on common pitfalls, gotchas, errors, and anti-patterns "
        "for this subtask.\n"
        "Populate `key_findings` richly with pitfalls, typical mistakes, error signatures, "
        "and anti-patterns to avoid; keep `code_examples` minimal (only counter-examples "
        "showing the pitfall, if needed). All fields below must still be present so "
        "downstream merging is uniform.\n\n"
        + _SUBAGENT_SCHEMA_FOOTER
    ),
}


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
        from azure.identity import AzureCliCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            AzureCliCredential(),
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
        input=[{"role": "user", "content": (
            f"Research the following topic thoroughly: {topic}\n\n"
            "IMPORTANT: If this topic is about a VS Code extension, focus on:\n"
            "- How to install it (Extensions sidebar → search → click Install)\n"
            "- No API keys or credentials are needed — just install and use\n"
            "- What agents/features it provides\n"
            "- Step-by-step workflow in VS Code (chat panel, terminal, editor)\n"
            "- Show the full VS Code IDE with explorer, editor, terminal, and chat panels"
        )}],
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


def _cache_key(
    topic: str, audience: str, research_cfg: dict, parallel: bool = False,
) -> str:
    """Compute a deterministic SHA-256 cache key from normalised inputs."""
    blob = json.dumps(
        {
            "topic": topic.strip().lower(),
            "audience": audience.strip().lower(),
            "model": research_cfg.get("model", ""),
            "max_sources": research_cfg.get("max_sources", 5),
            "parallel": parallel,
        },
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _load_cache(cache_dir: Path, key: str, ttl_days: int) -> ResearchResult | None:
    """Load a cached research result if it exists and has not expired."""
    cache_file = cache_dir / f"{key}.json"
    if not cache_file.exists():
        return None
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    cached_at = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
    if (datetime.now() - cached_at).days > ttl_days:
        logger.info("Cache expired for key %s", key[:12])
        return None
    return ResearchResult.model_validate(data)


def _write_cache(cache_dir: Path, key: str, result: ResearchResult) -> None:
    """Persist a research result to the cache directory with a timestamp."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = result.model_dump()
    data["_cached_at"] = datetime.now().isoformat()
    (cache_dir / f"{key}.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


def _merge_subagent_results(
    topic: str, named_results: list[tuple[str, ResearchResult]],
) -> ResearchResult:
    """Merge per-subagent ResearchResult objects with case-insensitive de-dup."""

    def _dedup_preserve_case(items: list[str], *, strip: bool = False) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            normalised = item.strip() if strip else item
            key = normalised.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalised if strip else item)
        return out

    merged_sources: list[str] = []
    merged_findings: list[str] = []
    merged_code: list[str] = []
    raw_chunks: list[str] = []

    for name, res in named_results:
        merged_sources.extend(res.sources)
        merged_findings.extend(res.key_findings)
        merged_code.extend(res.code_examples)
        raw_chunks.append(f"## {name}\n{res.raw_notes}\n")

    return ResearchResult(
        topic=topic,
        sources=_dedup_preserve_case(merged_sources),
        key_findings=_dedup_preserve_case(merged_findings),
        code_examples=_dedup_preserve_case(merged_code, strip=True),
        raw_notes="".join(raw_chunks),
    )


def _run_subagents_parallel(
    topic: str, audience: str, config: dict,
) -> ResearchResult:
    """Dispatch three focused research subagents in parallel and merge results."""
    research_cfg = _get_research_config(config)
    max_sources = research_cfg.get("max_sources", 5)
    per_agent_sources = max(2, max_sources // 3)

    subagent_cfg = dict(research_cfg)
    subagent_cfg["max_sources"] = per_agent_sources

    provider = research_cfg["provider"]
    client = _create_client(config)

    def _dispatch(name: str, template: str) -> tuple[str, ResearchResult]:
        system_prompt = template.format(
            audience=audience, max_sources=per_agent_sources,
        )
        if provider == "azure_openai":
            res = _research_azure(client, subagent_cfg, system_prompt, topic)
        else:
            res = _research_openai(client, subagent_cfg, system_prompt, topic)
        return name, res

    named_results: list[tuple[str, ResearchResult]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_dispatch, name, template): name
            for name, template in _SUBAGENT_PROMPTS.items()
        }
        try:
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    named_results.append(future.result())
                except Exception as exc:
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError(
                        f"Subagent {name} failed: {exc}",
                    ) from exc
        except RuntimeError:
            raise

    # Preserve a stable merge order (matches _SUBAGENT_PROMPTS insertion order).
    order = {name: idx for idx, name in enumerate(_SUBAGENT_PROMPTS)}
    named_results.sort(key=lambda pair: order[pair[0]])

    return _merge_subagent_results(topic, named_results)


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

    parallel = config.get("research", {}).get("parallel_subagents", True)

    # ── Cache lookup ─────────────────────────────────────────────────────
    cache_cfg = config.get("research", {}).get("cache", {})
    cache_enabled = cache_cfg.get("enabled", False)
    cache_dir: Path | None = None
    cache_key_hex: str | None = None

    if cache_enabled:
        cache_dir = Path(cache_cfg.get("cache_dir", "outputs/.research_cache"))
        _rcfg = _get_research_config(config)
        cache_key_hex = _cache_key(topic, audience, _rcfg, parallel=parallel)

        if not config.get("force_research", False):
            cached = _load_cache(cache_dir, cache_key_hex, cache_cfg.get("ttl_days", 7))
            if cached is not None:
                logger.info("Research cache hit for '%s'", topic)
                research_path = output_dir / "research.json"
                research_path.write_text(cached.model_dump_json(indent=2), encoding="utf-8")
                return StageResult(
                    stage="research",
                    success=True,
                    output_path=str(research_path),
                    metadata={"cache_hit": True},
                )

    research_cfg = _get_research_config(config)

    system_prompt = _SYSTEM_PROMPT.format(
        audience=audience,
        max_sources=research_cfg["max_sources"],
    )

    logger.info(
        "Starting research for topic: %s (provider=%s, parallel=%s)",
        topic, research_cfg["provider"], parallel,
    )

    try:
        if parallel:
            result = _run_subagents_parallel(topic, audience, config)
        else:
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

    # ── Cache write ──────────────────────────────────────────────────────
    if cache_enabled and cache_dir is not None and cache_key_hex is not None:
        _write_cache(cache_dir, cache_key_hex, result)

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

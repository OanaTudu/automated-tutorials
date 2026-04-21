"""Script generation stage using OpenAI Responses API with structured outputs.

Public entry point `generate_script` runs a plan-execute-review pipeline:
1. `_plan_outline` produces a `TutorialOutline` (structured).
2. `_execute_section` fills one `Section` per plan entry (parallel).
3. `_assemble_script` builds the final `TutorialScript`, validates it, and
   enforces a coverage gate against the research findings.
If any step fails (including coverage gaps twice in a row), the function falls
back to `_generate_script_single_call`, which preserves the original
single-LLM-call behavior for zero regression.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar

from jinja2 import Environment, FileSystemLoader
from openai import OpenAI
from pydantic import BaseModel

from .models import (
    Section,
    SectionEdit,
    SectionPlan,
    StageResult,
    TutorialOutline,
    TutorialScript,
)
from .quality_gates import validate_script

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_MAX_ATTEMPTS = 3
_MAX_PARALLEL_SECTIONS = 4

_T = TypeVar("_T", bound=BaseModel)


def _create_client(config: dict) -> OpenAI:
    """Create the appropriate OpenAI client based on provider config."""
    provider = config["script"].get("provider", "openai")
    if provider == "azure_openai":
        from azure.identity import AzureCliCredential, get_bearer_token_provider
        from openai import AzureOpenAI

        token_provider = get_bearer_token_provider(
            AzureCliCredential(),
            "https://cognitiveservices.azure.com/.default",
        )
        azure_cfg = config["script"].get("azure_openai", {})
        return AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_ad_token_provider=token_provider,
            api_version=azure_cfg.get("api_version", "2025-04-01-preview"),
        )
    return OpenAI()


# ── Structured LLM call helpers ─────────────────────────────────────────


def _call_structured_typed(
    client: OpenAI,
    config: dict,
    system_prompt: str,
    input_messages: list[dict[str, str]],
    provider: str,
    response_model: type[_T],
    model_override: str | None = None,
) -> _T:
    """Call the LLM for structured output of ``response_model`` type."""
    model = model_override or config["script"]["model"]
    max_tokens = config["script"]["max_output_tokens"]

    if provider == "azure_openai":
        messages = [{"role": "system", "content": system_prompt}, *input_messages]
        resp = client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_model,
            max_completion_tokens=max_tokens,
        )
        return resp.choices[0].message.parsed

    resp = client.responses.parse(
        model=model,
        instructions=system_prompt,
        input=input_messages,
        text_format=response_model,
        max_output_tokens=max_tokens,
    )
    return resp.output_parsed


def _call_structured(
    client: OpenAI,
    config: dict,
    system_prompt: str,
    input_messages: list[dict[str, str]],
    provider: str,
) -> TutorialScript:
    """Legacy helper — calls the LLM for a full `TutorialScript` in one shot."""
    return _call_structured_typed(
        client,
        config,
        system_prompt,
        input_messages,
        provider,
        response_model=TutorialScript,
    )


# ── Plan-execute-review helpers ─────────────────────────────────────────


def _planner_model(config: dict) -> str:
    return config["script"].get("planner_model") or config["script"]["model"]


def _executor_model(config: dict) -> str:
    return config["script"].get("executor_model") or config["script"]["model"]


def _extract_findings(source_material: str) -> list[str]:
    """Parse bullet lines under a ``Key findings:`` header in the formatted research block."""
    findings: list[str] = []
    in_section = False
    for raw_line in source_material.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("Key findings:"):
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("- "):
            findings.append(stripped[2:].strip())
            continue
        if stripped == "":
            continue
        # A new header (e.g., "Code examples:") ends the Key findings block.
        if stripped.endswith(":"):
            break
    return findings


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _coverage_gaps(
    sections: list[Section],
    research_findings: list[str],
) -> list[str]:
    """Return findings that don't appear (as substrings) in any section's text."""
    if not research_findings:
        return []
    haystack = " ".join(
        _normalize(p) for s in sections for p in (s.narration, *s.key_points)
    )
    return [f for f in research_findings if _normalize(f) and _normalize(f) not in haystack]


def _plan_outline(
    client: OpenAI,
    config: dict,
    provider: str,
    env: Environment,
    system_prompt: str,
    topic: str,
    audience: str,
    target_seconds: int,
    source_material: str,
) -> TutorialOutline:
    """Render the planner prompt and request a structured `TutorialOutline`."""
    user_prompt = env.get_template("tutorial_planner.jinja2").render(
        topic=topic,
        audience=audience,
        target_seconds=target_seconds,
        source_material=source_material,
    )
    messages = [{"role": "user", "content": user_prompt}]
    outline = _call_structured_typed(
        client,
        config,
        system_prompt,
        messages,
        provider,
        response_model=TutorialOutline,
        model_override=_planner_model(config),
    )
    if not isinstance(outline, TutorialOutline):
        raise RuntimeError(
            f"Planner returned unexpected type: {type(outline).__name__}",
        )
    return outline


def _execute_section(
    client: OpenAI,
    config: dict,
    provider: str,
    env: Environment,
    system_prompt: str,
    outline: TutorialOutline,
    plan: SectionPlan,
    audience: str,
    source_material: str,
    revision_context: str = "",
) -> Section:
    """Render the section prompt and request ONE structured `Section`.

    Wraps one ``_MAX_ATTEMPTS`` retry-with-``last_error`` loop per section.
    """
    last_error: str | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            user_prompt = env.get_template("tutorial_section.jinja2").render(
                outline=outline,
                section_plan=plan,
                audience=audience,
                source_material=source_material,
                revision_context=revision_context,
            )
            messages: list[dict[str, str]] = [{"role": "user", "content": user_prompt}]
            if last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Previous output failed validation: {last_error}. "
                            "Fix the issues and return valid JSON."
                        ),
                    },
                )
            section = _call_structured_typed(
                client,
                config,
                system_prompt,
                messages,
                provider,
                response_model=Section,
                model_override=_executor_model(config),
            )
            if not isinstance(section, Section):
                raise RuntimeError(
                    f"Executor returned unexpected type: {type(section).__name__}",
                )
            return section
        except Exception as exc:  # noqa: BLE001 — we retry on any executor error
            last_error = str(exc)
            logger.warning(
                "Section %s execution attempt %d failed: %s",
                plan.id,
                attempt + 1,
                exc,
            )
    raise RuntimeError(
        f"Section {plan.id} execution failed after {_MAX_ATTEMPTS} attempts: {last_error}",
    )


def _execute_sections_parallel(
    client: OpenAI,
    config: dict,
    provider: str,
    env: Environment,
    system_prompt: str,
    outline: TutorialOutline,
    audience: str,
    source_material: str,
    revision_contexts: dict[str, str] | None = None,
) -> dict[str, Section]:
    """Run `_execute_section` across the outline with a bounded thread pool."""
    revision_contexts = revision_contexts or {}
    max_workers = max(1, min(len(outline.sections), _MAX_PARALLEL_SECTIONS))
    results: dict[str, Section] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _execute_section,
                client,
                config,
                provider,
                env,
                system_prompt,
                outline,
                plan,
                audience,
                source_material,
                revision_contexts.get(plan.id, ""),
            ): plan.id
            for plan in outline.sections
        }
        try:
            for fut in list(futures):
                results[futures[fut]] = fut.result()
        except Exception:
            for fut in futures:
                fut.cancel()
            raise
    return results


def _assemble_script(
    outline: TutorialOutline,
    sections_by_id: dict[str, Section],
    research_findings: list[str],
    config: dict,
    audience: str,
) -> TutorialScript:
    """Assemble sections into a `TutorialScript`, validate, and enforce coverage."""
    ordered = [sections_by_id[p.id] for p in outline.sections]
    estimated_words = sum(len(s.narration.split()) for s in ordered)
    script = TutorialScript(
        topic=outline.topic,
        audience=outline.audience,
        total_target_seconds=outline.total_target_seconds,
        estimated_words=estimated_words,
        hook=outline.hook,
        sections=ordered,
        recap=outline.recap,
        cta=outline.cta,
    )
    max_seconds = config["pipeline"]["max_duration_seconds"]
    errors = validate_script(script, max_seconds=max_seconds, audience=audience)
    if errors:
        raise RuntimeError(f"validate_script errors: {'; '.join(errors)}")
    gaps = _coverage_gaps(ordered, research_findings)
    if gaps:
        raise RuntimeError(f"coverage gap: {'; '.join(gaps)}")
    return script


def _sections_needing_revision(
    outline: TutorialOutline,
    gaps: list[str],
) -> dict[str, str]:
    """Map section_id -> revision_context describing which gaps that section should cover."""
    result: dict[str, str] = {}
    for plan in outline.sections:
        matched: list[str] = []
        plan_text = _normalize(" ".join([plan.title, *plan.coverage_points]))
        for gap in gaps:
            norm = _normalize(gap)
            if any(tok in plan_text for tok in norm.split() if len(tok) > 3):
                matched.append(gap)
        if matched:
            result[plan.id] = (
                "The following research findings were missing from your previous "
                "output — please weave them into the narration or key_points:\n- "
                + "\n- ".join(matched)
            )
    if not result and outline.sections and gaps:
        result[outline.sections[0].id] = (
            "The following research findings were missing from the previous output "
            "— please weave them into the narration or key_points:\n- "
            + "\n- ".join(gaps)
        )
    return result


# ── Single-call fallback (original behavior) ─────────────────────────────


def _generate_script_single_call(
    topic: str,
    output_dir: Path,
    config: dict,
) -> StageResult:
    """Original single-LLM-call script generation — preserved as fallback path."""
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
            audience = config.get("audience", "")
            errors = validate_script(
                parsed, max_seconds=max_seconds, audience=audience,
            )
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


# ── Public entry point ──────────────────────────────────────────────────


def generate_script(
    topic: str,
    output_dir: Path,
    config: dict,
) -> StageResult:
    """Generate a tutorial script via plan-execute-review, falling back to a single call."""
    output_dir.mkdir(parents=True, exist_ok=True)
    audience = config.get("audience", "beginner developers")
    target_seconds = config["pipeline"]["max_duration_seconds"]
    source_material = config.get("source_material", "")
    research_findings = _extract_findings(source_material)

    try:
        client = _create_client(config)
        provider = config["script"].get("provider", "openai")
        env = Environment(
            loader=FileSystemLoader(str(_PROMPTS_DIR)),
            autoescape=False,
        )
        system_prompt = env.get_template("tutorial_system.jinja2").render(
            audience=audience,
            max_duration_seconds=target_seconds,
        )

        outline = _plan_outline(
            client,
            config,
            provider,
            env,
            system_prompt,
            topic,
            audience,
            target_seconds,
            source_material,
        )

        sections_by_id = _execute_sections_parallel(
            client, config, provider, env, system_prompt,
            outline, audience, source_material,
        )

        try:
            script = _assemble_script(
                outline, sections_by_id, research_findings, config, audience,
            )
        except RuntimeError as first_err:
            msg = str(first_err)
            if not msg.startswith("coverage gap:"):
                raise
            gaps = [g.strip() for g in msg[len("coverage gap:"):].split(";") if g.strip()]
            logger.warning(
                "Coverage gap on first assembly: %s. Re-executing affected sections.",
                gaps,
            )
            revision_ctx = _sections_needing_revision(outline, gaps)
            revised = _execute_sections_parallel(
                client, config, provider, env, system_prompt,
                outline, audience, source_material,
                revision_contexts=revision_ctx,
            )
            merged = {**sections_by_id, **revised}
            script = _assemble_script(
                outline, merged, research_findings, config, audience,
            )

        script_path = output_dir / "script.json"
        script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
        return StageResult(
            stage="script",
            success=True,
            output_path=str(script_path),
            metadata={
                "words": script.estimated_words,
                "sections": len(script.sections),
                "path": "plan_execute",
            },
        )
    except Exception as exc:  # noqa: BLE001 — deliberate catch-all for fallback
        logger.warning(
            "Plan-execute script generation failed (%s); falling back to single-call.",
            exc,
        )
        result = _generate_script_single_call(topic, output_dir, config)
        result.metadata["path"] = "single_call_fallback"
        return result


# ── Targeted revision (Phase 2) ─────────────────────────────────────────


def _section_to_plan(section: Section) -> SectionPlan:
    """Synthesize a `SectionPlan` from an already-executed `Section`."""
    return SectionPlan(
        id=section.id,
        title=section.title,
        target_seconds=section.target_seconds,
        coverage_points=list(section.key_points),
    )


def _outline_from_script(script: TutorialScript, plans: list[SectionPlan]) -> TutorialOutline:
    """Build a synthetic `TutorialOutline` from an existing script + section plans."""
    return TutorialOutline(
        topic=script.topic,
        audience=script.audience,
        total_target_seconds=script.total_target_seconds,
        sections=plans,
        hook=script.hook,
        recap=script.recap,
        cta=script.cta,
    )


def revise_script(
    script: TutorialScript,
    outline_plans: list[SectionPlan] | None,
    edits: list[SectionEdit],
    output_dir: Path,
    config: dict,
    audience: str,
    source_material: str,
    research_findings: list[str],  # noqa: ARG001 — reserved for coverage gating
) -> StageResult:
    """Regenerate only flagged sections of a script using reviewer-supplied edits.

    Unflagged sections are copied through by reference (byte-identical). Each
    valid edit is executed via `_execute_section` with the reviewer's issue and
    suggested change passed in as `revision_context`. Invalid indices are
    skipped with a warning.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build per-index SectionPlan list — synthesize from script when not provided.
    if outline_plans is None:
        plans_by_index = [_section_to_plan(s) for s in script.sections]
    else:
        plans_by_id = {p.id: p for p in outline_plans}
        plans_by_index = [
            plans_by_id.get(s.id, _section_to_plan(s)) for s in script.sections
        ]

    synthetic_outline = _outline_from_script(script, plans_by_index)

    client = _create_client(config)
    provider = config["script"].get("provider", "openai")
    env = Environment(
        loader=FileSystemLoader(str(_PROMPTS_DIR)),
        autoescape=False,
    )
    system_prompt = env.get_template("tutorial_system.jinja2").render(
        audience=audience,
        max_duration_seconds=config["pipeline"]["max_duration_seconds"],
    )

    revised: dict[int, Section] = {}
    revised_count = 0
    for edit in edits:
        idx = edit.section_index
        if idx >= len(script.sections) or idx < 0:
            logger.warning(
                "Skipping section_edit with out-of-range index %d (script has %d sections)",
                idx, len(script.sections),
            )
            continue
        if idx in revised:
            # Duplicate edits for the same index — keep the first revision.
            logger.warning(
                "Duplicate section_edit for index %d; keeping first revision", idx,
            )
            continue
        plan = plans_by_index[idx]
        revision_context = (
            f"Reviewer issue: {edit.issue}\n"
            f"Suggested change: {edit.suggested_change}"
        )
        revised[idx] = _execute_section(
            client,
            config,
            provider,
            env,
            system_prompt,
            synthetic_outline,
            plan,
            audience,
            source_material,
            revision_context=revision_context,
        )
        revised_count += 1

    # Reassemble: flagged sections use regenerated Section, unflagged copy by reference.
    new_sections: list[Section] = [
        revised[i] if i in revised else script.sections[i]
        for i in range(len(script.sections))
    ]
    estimated_words = sum(len(s.narration.split()) for s in new_sections)
    revised_script = TutorialScript(
        topic=script.topic,
        audience=script.audience,
        total_target_seconds=script.total_target_seconds,
        estimated_words=estimated_words,
        hook=script.hook,
        sections=new_sections,
        recap=script.recap,
        cta=script.cta,
    )

    errors = validate_script(
        revised_script,
        max_seconds=config["pipeline"]["max_duration_seconds"],
        audience=audience,
    )
    if errors:
        raise RuntimeError(f"validate_script errors after revision: {'; '.join(errors)}")

    script_path = output_dir / "script.json"
    script_path.write_text(revised_script.model_dump_json(indent=2), encoding="utf-8")
    return StageResult(
        stage="script",
        success=True,
        output_path=str(script_path),
        metadata={
            "words": revised_script.estimated_words,
            "sections": len(revised_script.sections),
            "path": "revise",
            "revised_sections": revised_count,
        },
    )

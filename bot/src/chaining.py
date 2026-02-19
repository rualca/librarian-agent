"""Agent chaining module.

Allows running a sequence of OpenCode agents where each agent receives
the output of the previous one as context.  Chains are defined as
configuration and executed within a single OpenCode session.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from src import opencode
from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
MAX_STEP_OUTPUT_CHARS = 12_000
MAX_FINAL_OUTPUT_CHARS = 20_000


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class ChainStep:
    agent: str
    instruction: str | None = None  # extra instruction for this step


@dataclass
class ChainResult:
    success: bool
    output: str
    steps_completed: int
    steps_total: int
    failed_step: str | None = None
    error: str | None = None
    step_outputs: list[tuple[str, str]] = field(default_factory=list)  # (agent, output)


# ---------------------------------------------------------------------------
# Built-in chains
# ---------------------------------------------------------------------------
BUILTIN_CHAINS: dict[str, list[ChainStep]] = {
    "ingest_and_connect": [
        ChainStep(
            agent="librarian",
            instruction="Process the user's input and create/update the appropriate Encounter note.",
        ),
        ChainStep(
            agent="connector",
            instruction="Based on what was just captured, find connections to existing Cards and MOCs.",
        ),
    ],
    "full_review": [
        ChainStep(
            agent="reviewer",
            instruction="Audit the vault for structural issues, broken links, and inconsistent tags.",
        ),
        ChainStep(
            agent="archivist",
            instruction="Based on the review above, identify stale content and suggest archival actions.",
        ),
    ],
    "capture_and_write": [
        ChainStep(
            agent="librarian",
            instruction="Process the user's input into the vault.",
        ),
        ChainStep(
            agent="writer",
            instruction="Based on what was just captured, draft a short synthesis connecting it to existing knowledge.",
        ),
    ],
    "capture_and_quiz": [
        ChainStep(
            agent="librarian",
            instruction="Process the user's input and create/update the appropriate Encounter note.",
        ),
        ChainStep(
            agent="examiner",
            instruction="Based on what was just captured, generate 2-3 quick recall questions to reinforce the new knowledge immediately.",
        ),
    ],
}


def get_chain(name: str) -> list[ChainStep] | None:
    """Look up a chain by name.  Returns None if not found."""
    return BUILTIN_CHAINS.get(name)


def list_chains() -> list[dict]:
    """Return metadata about all available chains."""
    result = []
    for name, steps in BUILTIN_CHAINS.items():
        result.append({
            "name": name,
            "steps": [s.agent for s in steps],
            "description": " → ".join(s.agent for s in steps),
        })
    return result


# ---------------------------------------------------------------------------
# Chain execution
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int) -> str:
    """Truncate text to *limit* characters, appending a marker."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n…[truncated]"


async def execute_chain(
    prompt: str,
    chain: list[ChainStep],
    images: list[tuple[bytes, str]] | None = None,
    session_title: str | None = None,
) -> ChainResult:
    """Execute a multi-agent chain within one OpenCode session.

    Flow:
    1.  Start the OpenCode server and create a session.
    2.  If ``images`` are supplied, extract their content via the vision
        model first (same two-step process as ``execute_task``).
    3.  For each step in *chain*:
        a.  Build a prompt that includes the original user request **and**
            the previous step's output (if any).
        b.  Send to the step's agent.
        c.  On failure → stop, record the error, return partial result.
        d.  Truncate oversized outputs before forwarding.
    4.  Return the final ``ChainResult``.
    """
    client = opencode.get_client()
    steps_total = len(chain)

    try:
        await client.start_server()
    except Exception as exc:
        return ChainResult(
            success=False,
            output="",
            steps_completed=0,
            steps_total=steps_total,
            failed_step="server_start",
            error=str(exc),
        )

    title = session_title or f"chain: {' → '.join(s.agent for s in chain)}"
    try:
        session = await client.create_session(title=title)
    except Exception as exc:
        return ChainResult(
            success=False,
            output="",
            steps_completed=0,
            steps_total=steps_total,
            failed_step="create_session",
            error=str(exc),
        )

    session_id = session["id"]
    default_model = {
        "providerID": opencode.OPENCODE_PROVIDER_ID,
        "modelID": opencode.OPENCODE_MODEL_ID,
    }

    # --- Optional vision pre-processing ---
    extracted_image_text: str | None = None
    if images:
        try:
            extracted_image_text = await client._extract_text_from_images(
                session_id, images, context=prompt,
            )
        except Exception as exc:
            return ChainResult(
                success=False,
                output="",
                steps_completed=0,
                steps_total=steps_total,
                failed_step="vision_extraction",
                error=str(exc),
            )

    # --- Run chain steps ---
    step_outputs: list[tuple[str, str]] = []
    prev_output: str | None = None

    for idx, step in enumerate(chain):
        parts: list[str] = []

        # Original user request
        parts.append(f"## User request\n{prompt}")

        # Image extraction (only on first step)
        if extracted_image_text and idx == 0:
            parts.append(
                f"\n## Extracted image content\n{extracted_image_text}"
            )

        # Previous step output
        if prev_output:
            prev_agent = chain[idx - 1].agent
            truncated = _truncate(prev_output, MAX_STEP_OUTPUT_CHARS)
            parts.append(
                f"\n## Previous step ({prev_agent}) output\n{truncated}"
            )

        # Step-specific instruction
        if step.instruction:
            parts.append(f"\n## Your task\n{step.instruction}")

        # Chain awareness
        remaining = [s.agent for s in chain[idx + 1:]]
        if remaining:
            parts.append(
                f"\n*(Note: after you, the following agents will process this: "
                f"{', '.join(remaining)}. Keep your output structured for them.)*"
            )

        step_prompt = "\n".join(parts)

        try:
            response = await client.send_message(
                session_id, step_prompt, agent=step.agent, model=default_model,
            )
            output = client._extract_text_parts(response)
        except Exception as exc:
            logger.error("Chain step %d (%s) failed: %s", idx, step.agent, exc)
            return ChainResult(
                success=False,
                output=_truncate(
                    "\n\n---\n\n".join(f"**[{a}]**\n{o}" for a, o in step_outputs),
                    MAX_FINAL_OUTPUT_CHARS,
                ) if step_outputs else "",
                steps_completed=idx,
                steps_total=steps_total,
                failed_step=step.agent,
                error=str(exc),
                step_outputs=step_outputs,
            )

        step_outputs.append((step.agent, output))
        prev_output = output
        logger.info("Chain step %d/%d (%s) completed", idx + 1, steps_total, step.agent)

    # --- Assemble final output ---
    if len(step_outputs) == 1:
        final = step_outputs[0][1]
    else:
        sections = []
        for agent_name, output in step_outputs:
            sections.append(f"**[{agent_name}]**\n{output}")
        final = "\n\n---\n\n".join(sections)

    return ChainResult(
        success=True,
        output=_truncate(final, MAX_FINAL_OUTPUT_CHARS),
        steps_completed=steps_total,
        steps_total=steps_total,
        step_outputs=step_outputs,
    )

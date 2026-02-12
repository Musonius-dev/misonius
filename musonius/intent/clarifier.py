"""Scout-based clarifying question generation for the Intent Engine."""

from __future__ import annotations

import json
import logging
from typing import Any

from musonius.intent.engine import Question, make_question_id
from musonius.orchestration.router import ModelRouter

logger = logging.getLogger(__name__)

_SCOUT_PROMPT_TEMPLATE = """\
You are analyzing a task description to generate clarifying questions.

Task: {task_description}

{context_section}

Generate 3-5 targeted questions that will help refine this task. Focus on:
- Business goals and user impact
- Technical constraints and architecture needs
- Edge cases and error scenarios
- Success criteria

For each question, explain why it matters for implementation planning.

Return ONLY valid JSON — no markdown, no code blocks, no extra text:
[
  {{
    "category": "business",
    "question": "...",
    "why_asking": "..."
  }},
  {{
    "category": "architecture",
    "question": "...",
    "why_asking": "..."
  }}
]

Valid categories: "business", "architecture", "constraints", "edge_cases"
"""


def generate_questions_via_scout(
    router: ModelRouter,
    task_description: str,
    context: dict[str, str],
) -> list[Question]:
    """Generate clarifying questions using the scout model (free/cheap tier).

    Falls back to rule-based question generation if the scout model call fails.

    Args:
        router: Model router for LLM calls.
        task_description: User's task description.
        context: Additional context (repo_map, conventions, etc.).

    Returns:
        List of 3-5 Question objects.
    """
    try:
        return _generate_via_llm(router, task_description, context)
    except Exception as e:
        logger.warning("Scout question generation failed, falling back to rules: %s", e)
        return _generate_fallback_questions(task_description)


def _generate_via_llm(
    router: ModelRouter,
    task_description: str,
    context: dict[str, str],
) -> list[Question]:
    """Generate questions via the scout LLM model.

    Args:
        router: Model router for LLM calls.
        task_description: User's task description.
        context: Additional context.

    Returns:
        List of Question objects parsed from the scout model response.

    Raises:
        RuntimeError: If the model call fails after retries.
        ValueError: If the response cannot be parsed.
    """
    context_section = _build_context_section(context)
    prompt = _SCOUT_PROMPT_TEMPLATE.format(
        task_description=task_description,
        context_section=context_section,
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant that generates clarifying questions for software development tasks. Always respond with valid JSON."},
        {"role": "user", "content": prompt},
    ]

    response = router.call_scout(messages, temperature=0.3, max_tokens=1024)
    questions = _parse_questions_response(response.content)

    if not questions:
        raise ValueError("Scout model returned no valid questions")

    return questions


def _build_context_section(context: dict[str, str]) -> str:
    """Build the context section for the scout prompt.

    Args:
        context: Dict of context key-value pairs.

    Returns:
        Formatted context section string.
    """
    if not context:
        return ""

    parts = ["Additional context:"]
    for key, value in context.items():
        if value:
            parts.append(f"\n{key}:\n{value}")
    return "\n".join(parts)


def _parse_questions_response(response_text: str) -> list[Question]:
    """Parse the scout model response into Question objects.

    Handles both raw JSON and markdown-wrapped JSON responses.

    Args:
        response_text: Raw text from the scout model.

    Returns:
        List of parsed Question objects.
    """
    parsed = _extract_json_array(response_text)
    if not isinstance(parsed, list):
        logger.warning("Expected JSON array, got %s", type(parsed).__name__)
        return []

    questions: list[Question] = []
    valid_categories = {"business", "architecture", "constraints", "edge_cases"}

    for item in parsed:
        if not isinstance(item, dict):
            continue

        category = item.get("category", "").strip()
        question_text = item.get("question", "").strip()
        why_asking = item.get("why_asking", "").strip()

        if not question_text:
            continue

        # Normalize unknown categories
        if category not in valid_categories:
            category = "business"

        questions.append(
            Question(
                id=make_question_id(),
                category=category,
                question=question_text,
                why_asking=why_asking,
            )
        )

    # Enforce 3-5 question limit
    return questions[:5]


def _extract_json_array(text: str) -> Any:
    """Extract a JSON array from text, handling markdown code blocks.

    Args:
        text: Raw response text.

    Returns:
        Parsed JSON value.

    Raises:
        ValueError: If no valid JSON can be extracted.
    """
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from code block
    if "```" in text:
        blocks = text.split("```")
        for block in blocks:
            clean = block.strip()
            if clean.startswith("json"):
                clean = clean[4:].strip()
            try:
                return json.loads(clean)
            except json.JSONDecodeError:
                continue

    # Try finding array brackets
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


def _generate_fallback_questions(task_description: str) -> list[Question]:
    """Generate rule-based fallback questions when the scout model is unavailable.

    Args:
        task_description: User's task description.

    Returns:
        List of 3-5 generic but useful Question objects.
    """
    questions: list[Question] = []
    desc_lower = task_description.lower()
    words = task_description.split()

    # Always ask about business goals
    questions.append(
        Question(
            id=make_question_id(),
            category="business",
            question="What problem does this solve, and who are the primary users?",
            why_asking="Understanding the business context helps prioritize implementation decisions.",
        )
    )

    # Ask for detail if description is short
    if len(words) < 10:
        questions.append(
            Question(
                id=make_question_id(),
                category="business",
                question="Could you provide more detail about the expected behavior and outcomes?",
                why_asking="Short descriptions often have implicit requirements that need to be surfaced.",
            )
        )

    # Ask about architecture if no specific files/modules mentioned
    if not any(word in desc_lower for word in ["file", "module", "component", "class", "function"]):
        questions.append(
            Question(
                id=make_question_id(),
                category="architecture",
                question="Which files, modules, or components should be affected by this change?",
                why_asking="Knowing the scope helps identify dependencies and potential conflicts.",
            )
        )

    # Ask about constraints
    questions.append(
        Question(
            id=make_question_id(),
            category="constraints",
            question="Are there any performance requirements, backward compatibility needs, or other constraints?",
            why_asking="Constraints shape the implementation approach and prevent rework.",
        )
    )

    # Ask about edge cases
    if not any(word in desc_lower for word in ["error", "fail", "edge", "invalid"]):
        questions.append(
            Question(
                id=make_question_id(),
                category="edge_cases",
                question="What should happen in error scenarios or with invalid input?",
                why_asking="Handling edge cases upfront prevents bugs and improves robustness.",
            )
        )

    return questions[:5]

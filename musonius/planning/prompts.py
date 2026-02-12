"""Prompt templates for the planning engine."""

from __future__ import annotations

PLAN_SYSTEM_PROMPT = """\
You are a technical planning assistant for software engineering tasks.
Generate detailed, file-level implementation plans.

Output ONLY valid JSON matching this schema:
{
  "phases": [
    {
      "id": "phase-1",
      "title": "Phase title",
      "description": "What this phase accomplishes",
      "files": [
        {
          "path": "relative/path/to/file.py",
          "action": "create|modify|delete",
          "description": "What changes to make",
          "key_changes": ["specific change 1", "specific change 2"]
        }
      ],
      "acceptance_criteria": ["criterion 1", "criterion 2"],
      "test_strategy": "How to test this phase"
    }
  ]
}

Rules:
- Be specific about file paths (use existing paths from the repo map)
- Each phase should be independently testable
- Acceptance criteria must be concrete and verifiable
- Include a test strategy for each phase
"""

PLAN_USER_TEMPLATE = """\
## Task
{task_description}

## Codebase Context
{repo_map}

## Past Decisions
{decisions}

## Conventions
{conventions}

## Past Failures (Avoid These Approaches)
{failures}

## Instructions
Generate a file-level implementation plan with {max_phases} phase(s).
For each file, describe the key changes needed.
Include acceptance criteria and test strategy.
"""


def build_plan_prompt(
    task_description: str,
    repo_map: str = "",
    decisions: str = "",
    conventions: str = "",
    failures: str = "",
    max_phases: int = 1,
) -> list[dict[str, str]]:
    """Build the messages list for plan generation.

    Args:
        task_description: The task to plan for.
        repo_map: Repo map context string.
        decisions: Past decisions context.
        conventions: Coding conventions context.
        failures: Past failures context to avoid repeating.
        max_phases: Maximum number of phases.

    Returns:
        Messages list in OpenAI chat format.
    """
    user_content = PLAN_USER_TEMPLATE.format(
        task_description=task_description,
        repo_map=repo_map or "(no repo map available)",
        decisions=decisions or "(no past decisions)",
        conventions=conventions or "(no conventions recorded)",
        failures=failures or "(no known failures)",
        max_phases=max_phases,
    )

    return [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

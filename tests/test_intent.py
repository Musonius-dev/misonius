"""Tests for the Intent Engine (L1) — data models, engine, and clarifier."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from musonius.intent.clarifier import (
    _extract_json_array,
    _generate_fallback_questions,
    _parse_questions_response,
    generate_questions_via_scout,
)
from musonius.intent.engine import Intent, IntentEngine, Question, make_question_id

# ---------------------------------------------------------------------------
# Question dataclass
# ---------------------------------------------------------------------------


class TestQuestion:
    """Tests for the Question dataclass."""

    def test_create_question(self) -> None:
        """Should create a Question with all fields."""
        q = Question(
            id="q-abc123",
            category="business",
            question="What problem does this solve?",
            why_asking="Understanding business context helps prioritize.",
        )
        assert q.id == "q-abc123"
        assert q.category == "business"
        assert q.question == "What problem does this solve?"
        assert q.why_asking == "Understanding business context helps prioritize."

    def test_valid_categories(self) -> None:
        """Should accept all valid question categories."""
        for category in ("business", "architecture", "constraints", "edge_cases"):
            q = Question(id="q-1", category=category, question="?", why_asking="reason")
            assert q.category == category


# ---------------------------------------------------------------------------
# Intent dataclass
# ---------------------------------------------------------------------------


class TestIntent:
    """Tests for the Intent dataclass."""

    def test_create_basic_intent(self) -> None:
        """Should create an intent with just a task description."""
        intent = Intent(task_description="Add rate limiting to the API")
        assert intent.task_description == "Add rate limiting to the API"
        assert intent.business_goals == []
        assert intent.technical_constraints == []
        assert intent.edge_cases == []
        assert intent.success_criteria == []
        assert intent.clarification_history == []
        assert intent.created_at is not None

    def test_is_refined_false_when_no_history(self) -> None:
        """Should report not refined when no clarification history."""
        intent = Intent(task_description="fix a bug")
        assert intent.is_refined is False

    def test_is_refined_true_with_history(self) -> None:
        """Should report refined when clarification history exists."""
        q = Question(id="q-1", category="business", question="?", why_asking="reason")
        intent = Intent(
            task_description="fix a bug",
            clarification_history=[(q, "It's a login bug")],
        )
        assert intent.is_refined is True

    def test_is_valid_requires_success_criteria(self) -> None:
        """Should be invalid without success criteria."""
        intent = Intent(task_description="do something")
        assert intent.is_valid is False

    def test_is_valid_with_criteria(self) -> None:
        """Should be valid with task description and success criteria."""
        intent = Intent(
            task_description="do something",
            success_criteria=["Tests pass"],
        )
        assert intent.is_valid is True

    def test_is_valid_fails_empty_description(self) -> None:
        """Should be invalid with empty task description."""
        intent = Intent(
            task_description="   ",
            success_criteria=["Tests pass"],
        )
        assert intent.is_valid is False

    def test_summary_basic(self) -> None:
        """Should generate a summary with task description."""
        intent = Intent(task_description="Add caching")
        summary = intent.summary()
        assert "Task: Add caching" in summary

    def test_summary_includes_all_sections(self) -> None:
        """Should include all populated sections in the summary."""
        q = Question(id="q-1", category="business", question="Why?", why_asking="reason")
        intent = Intent(
            task_description="Add caching",
            business_goals=["Reduce latency"],
            technical_constraints=["Must use Redis"],
            edge_cases=["Cache miss handling"],
            success_criteria=["P95 < 100ms"],
            clarification_history=[(q, "To speed up API")],
        )
        summary = intent.summary()
        assert "Business Goals:" in summary
        assert "Reduce latency" in summary
        assert "Technical Constraints:" in summary
        assert "Must use Redis" in summary
        assert "Edge Cases:" in summary
        assert "Cache miss handling" in summary
        assert "Success Criteria:" in summary
        assert "P95 < 100ms" in summary
        assert "Clarifications:" in summary
        assert "Why?" in summary
        assert "To speed up API" in summary


# ---------------------------------------------------------------------------
# make_question_id
# ---------------------------------------------------------------------------


class TestMakeQuestionId:
    """Tests for question ID generation."""

    def test_format(self) -> None:
        """Should generate IDs in q-{hex} format."""
        qid = make_question_id()
        assert qid.startswith("q-")
        assert len(qid) == 10  # q- + 8 hex chars

    def test_uniqueness(self) -> None:
        """Should generate unique IDs."""
        ids = {make_question_id() for _ in range(100)}
        assert len(ids) == 100


# ---------------------------------------------------------------------------
# IntentEngine
# ---------------------------------------------------------------------------


def _make_router(scout_response: str = "[]") -> MagicMock:
    """Create a mocked ModelRouter that returns a specified scout response."""
    router = MagicMock()
    router.call_scout.return_value = SimpleNamespace(content=scout_response)
    return router


class TestIntentEngineCapture:
    """Tests for IntentEngine.capture_intent."""

    def test_captures_task_description(self) -> None:
        """Should capture the task description."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = engine.capture_intent("Add rate limiting")
        assert intent.task_description == "Add rate limiting"

    def test_strips_whitespace(self) -> None:
        """Should strip whitespace from the task description."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = engine.capture_intent("  Add rate limiting  ")
        assert intent.task_description == "Add rate limiting"

    def test_returns_unrefined_intent(self) -> None:
        """Captured intent should not be refined initially."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = engine.capture_intent("fix a bug")
        assert intent.is_refined is False


class TestIntentEngineClarify:
    """Tests for IntentEngine.ask_clarifying_questions."""

    def test_generates_questions_via_scout(self) -> None:
        """Should call the scout model and return parsed questions."""
        questions_json = json.dumps([
            {
                "category": "business",
                "question": "What API endpoints need rate limiting?",
                "why_asking": "To scope the implementation.",
            },
            {
                "category": "constraints",
                "question": "What rate limit threshold?",
                "why_asking": "To configure the limiter correctly.",
            },
        ])
        router = _make_router(scout_response=questions_json)
        engine = IntentEngine(router=router)

        questions = engine.ask_clarifying_questions("Add rate limiting")
        assert len(questions) == 2
        assert questions[0].category == "business"
        assert "rate limiting" in questions[0].question.lower()
        router.call_scout.assert_called_once()

    def test_falls_back_on_scout_failure(self) -> None:
        """Should return fallback questions when the scout model fails."""
        router = MagicMock()
        router.call_scout.side_effect = RuntimeError("Scout unavailable")
        engine = IntentEngine(router=router)

        questions = engine.ask_clarifying_questions("Add rate limiting")
        assert len(questions) >= 3  # Fallback always returns 3-5 questions
        assert all(isinstance(q, Question) for q in questions)

    def test_passes_context_to_scout(self) -> None:
        """Should pass context to the scout prompt."""
        questions_json = json.dumps([
            {"category": "business", "question": "?", "why_asking": "reason"},
        ])
        router = _make_router(scout_response=questions_json)
        engine = IntentEngine(router=router)

        engine.ask_clarifying_questions(
            "Add rate limiting",
            context={"repo_map": "file1.py\nfile2.py"},
        )
        # Verify scout was called (context is embedded in the prompt)
        router.call_scout.assert_called_once()


class TestIntentEngineRefine:
    """Tests for IntentEngine.refine_intent."""

    def test_refines_with_business_answer(self) -> None:
        """Should categorize business answers into business_goals."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")

        questions = [
            Question(id="q-1", category="business", question="Why?", why_asking="reason"),
        ]
        answers = {"q-1": "To reduce response times for end users"}

        refined = engine.refine_intent(intent, answers, questions)
        assert "To reduce response times for end users" in refined.business_goals
        assert refined.is_refined

    def test_refines_with_architecture_answer(self) -> None:
        """Should categorize architecture answers into technical_constraints."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")

        questions = [
            Question(id="q-1", category="architecture", question="What stack?", why_asking="reason"),
        ]
        answers = {"q-1": "Must use Redis with a 5-minute TTL"}

        refined = engine.refine_intent(intent, answers, questions)
        assert "Must use Redis with a 5-minute TTL" in refined.technical_constraints

    def test_refines_with_constraints_answer(self) -> None:
        """Should categorize constraint answers into technical_constraints."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")

        questions = [
            Question(id="q-1", category="constraints", question="Backward compat?", why_asking="r"),
        ]
        answers = {"q-1": "Must keep existing API contract"}

        refined = engine.refine_intent(intent, answers, questions)
        assert "Must keep existing API contract" in refined.technical_constraints

    def test_refines_with_edge_cases_answer(self) -> None:
        """Should categorize edge case answers into edge_cases."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")

        questions = [
            Question(id="q-1", category="edge_cases", question="Error handling?", why_asking="r"),
        ]
        answers = {"q-1": "Return stale cache on backend failure"}

        refined = engine.refine_intent(intent, answers, questions)
        assert "Return stale cache on backend failure" in refined.edge_cases

    def test_derives_success_criteria_from_goals(self) -> None:
        """Should derive success criteria from business goals when none given."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")

        questions = [
            Question(id="q-1", category="business", question="Why?", why_asking="reason"),
        ]
        answers = {"q-1": "Reduce latency by 50%"}

        refined = engine.refine_intent(intent, answers, questions)
        assert len(refined.success_criteria) > 0
        assert "Reduce latency by 50%" in refined.success_criteria[0]

    def test_preserves_existing_fields(self) -> None:
        """Should preserve existing fields when refining."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(
            task_description="Add caching",
            business_goals=["Existing goal"],
            success_criteria=["Existing criterion"],
        )

        questions = [
            Question(id="q-1", category="business", question="Why?", why_asking="reason"),
        ]
        answers = {"q-1": "New goal"}

        refined = engine.refine_intent(intent, answers, questions)
        assert "Existing goal" in refined.business_goals
        assert "New goal" in refined.business_goals
        assert "Existing criterion" in refined.success_criteria

    def test_skips_empty_answers(self) -> None:
        """Should skip questions with empty answers."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")

        questions = [
            Question(id="q-1", category="business", question="Why?", why_asking="reason"),
            Question(id="q-2", category="architecture", question="How?", why_asking="reason"),
        ]
        answers = {"q-1": "", "q-2": "Use Redis"}

        refined = engine.refine_intent(intent, answers, questions)
        assert len(refined.clarification_history) == 1  # Only q-2

    def test_skips_unknown_question_ids(self) -> None:
        """Should skip answers for question IDs not in the question list."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")

        questions = [
            Question(id="q-1", category="business", question="Why?", why_asking="reason"),
        ]
        answers = {"q-unknown": "Some answer", "q-1": "Real answer"}

        refined = engine.refine_intent(intent, answers, questions)
        assert len(refined.clarification_history) == 1


class TestIntentEngineValidate:
    """Tests for IntentEngine.validate_intent."""

    def test_valid_intent(self) -> None:
        """Should return no warnings for a fully populated intent."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(
            task_description="Add caching",
            success_criteria=["Tests pass"],
            technical_constraints=["Use Redis"],
            edge_cases=["Cache miss"],
        )
        assert engine.validate_intent(intent) == []

    def test_empty_description_warning(self) -> None:
        """Should warn on empty task description."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="")
        warnings = engine.validate_intent(intent)
        assert any("empty" in w.lower() for w in warnings)

    def test_no_success_criteria_warning(self) -> None:
        """Should warn when no success criteria defined."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(task_description="Add caching")
        warnings = engine.validate_intent(intent)
        assert any("success criteria" in w.lower() for w in warnings)

    def test_no_constraints_soft_warning(self) -> None:
        """Should give soft warning about missing constraints."""
        router = _make_router()
        engine = IntentEngine(router=router)
        intent = Intent(
            task_description="Add caching",
            success_criteria=["Tests pass"],
        )
        warnings = engine.validate_intent(intent)
        assert any("constraint" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Clarifier — _extract_json_array
# ---------------------------------------------------------------------------


class TestExtractJsonArray:
    """Tests for JSON extraction from LLM responses."""

    def test_parses_raw_json(self) -> None:
        """Should parse a raw JSON array."""
        data = [{"category": "business", "question": "?", "why_asking": "reason"}]
        result = _extract_json_array(json.dumps(data))
        assert result == data

    def test_parses_code_block(self) -> None:
        """Should extract JSON from markdown code block."""
        text = '```json\n[{"category": "business"}]\n```'
        result = _extract_json_array(text)
        assert result == [{"category": "business"}]

    def test_parses_bare_code_block(self) -> None:
        """Should extract JSON from bare code block without language tag."""
        text = '```\n[{"category": "business"}]\n```'
        result = _extract_json_array(text)
        assert result == [{"category": "business"}]

    def test_extracts_brackets_from_text(self) -> None:
        """Should find JSON array by bracket matching as last resort."""
        text = 'Here are the questions: [{"category": "business"}] hope that helps!'
        result = _extract_json_array(text)
        assert result == [{"category": "business"}]

    def test_raises_on_invalid_json(self) -> None:
        """Should raise ValueError when no JSON can be extracted."""
        with pytest.raises(ValueError, match="Could not extract JSON"):
            _extract_json_array("This is just plain text")


# ---------------------------------------------------------------------------
# Clarifier — _parse_questions_response
# ---------------------------------------------------------------------------


class TestParseQuestionsResponse:
    """Tests for parsing scout model responses into Question objects."""

    def test_parses_valid_response(self) -> None:
        """Should parse a valid JSON response into Question objects."""
        data = [
            {
                "category": "business",
                "question": "What problem does this solve?",
                "why_asking": "To understand impact.",
            },
            {
                "category": "architecture",
                "question": "What components are affected?",
                "why_asking": "To scope the changes.",
            },
        ]
        questions = _parse_questions_response(json.dumps(data))
        assert len(questions) == 2
        assert questions[0].category == "business"
        assert questions[1].category == "architecture"

    def test_normalizes_unknown_category(self) -> None:
        """Should normalize unknown categories to 'business'."""
        data = [{"category": "unknown", "question": "?", "why_asking": "reason"}]
        questions = _parse_questions_response(json.dumps(data))
        assert questions[0].category == "business"

    def test_skips_empty_questions(self) -> None:
        """Should skip entries with empty question text."""
        data = [
            {"category": "business", "question": "", "why_asking": "reason"},
            {"category": "business", "question": "Valid?", "why_asking": "reason"},
        ]
        questions = _parse_questions_response(json.dumps(data))
        assert len(questions) == 1

    def test_limits_to_five(self) -> None:
        """Should limit output to 5 questions max."""
        data = [
            {"category": "business", "question": f"Q{i}?", "why_asking": "reason"}
            for i in range(8)
        ]
        questions = _parse_questions_response(json.dumps(data))
        assert len(questions) == 5

    def test_generates_unique_ids(self) -> None:
        """Should generate unique IDs for each question."""
        data = [
            {"category": "business", "question": f"Q{i}?", "why_asking": "reason"}
            for i in range(3)
        ]
        questions = _parse_questions_response(json.dumps(data))
        ids = [q.id for q in questions]
        assert len(set(ids)) == 3

    def test_handles_non_array_response(self) -> None:
        """Should return empty list for non-array JSON."""
        questions = _parse_questions_response('{"not": "an array"}')
        assert questions == []

    def test_handles_non_dict_items(self) -> None:
        """Should skip non-dict items in the array."""
        data = ["not a dict", {"category": "business", "question": "Valid?", "why_asking": "r"}]
        questions = _parse_questions_response(json.dumps(data))
        assert len(questions) == 1


# ---------------------------------------------------------------------------
# Clarifier — fallback questions
# ---------------------------------------------------------------------------


class TestFallbackQuestions:
    """Tests for rule-based fallback question generation."""

    def test_always_asks_business_goal(self) -> None:
        """Should always include a business goal question."""
        questions = _generate_fallback_questions("Add rate limiting to the API")
        categories = [q.category for q in questions]
        assert "business" in categories

    def test_asks_more_detail_for_short_descriptions(self) -> None:
        """Should ask for more detail when description is very short."""
        questions = _generate_fallback_questions("fix bug")
        question_texts = [q.question.lower() for q in questions]
        assert any("more detail" in q for q in question_texts)

    def test_asks_about_scope_when_no_files_mentioned(self) -> None:
        """Should ask about affected files when none mentioned."""
        questions = _generate_fallback_questions("add rate limiting")
        categories = [q.category for q in questions]
        assert "architecture" in categories

    def test_always_asks_about_constraints(self) -> None:
        """Should always include a constraints question."""
        questions = _generate_fallback_questions("Add a new feature to handle auth")
        categories = [q.category for q in questions]
        assert "constraints" in categories

    def test_asks_edge_cases_when_not_mentioned(self) -> None:
        """Should ask about edge cases when not in the description."""
        questions = _generate_fallback_questions("add caching layer")
        categories = [q.category for q in questions]
        assert "edge_cases" in categories

    def test_skips_edge_cases_when_mentioned(self) -> None:
        """Should not ask about edge cases when description mentions error handling."""
        questions = _generate_fallback_questions("handle error cases in the login flow")
        # Should have fewer questions since edge cases are already addressed
        assert len(questions) <= 5

    def test_returns_max_five(self) -> None:
        """Should never return more than 5 questions."""
        questions = _generate_fallback_questions("x")  # Very short
        assert len(questions) <= 5

    def test_returns_at_least_three(self) -> None:
        """Should return at least 3 questions for any input."""
        questions = _generate_fallback_questions("Add rate limiting to the public API endpoints")
        assert len(questions) >= 3

    def test_all_questions_have_valid_fields(self) -> None:
        """All fallback questions should have all required fields."""
        questions = _generate_fallback_questions("implement search feature")
        for q in questions:
            assert q.id.startswith("q-")
            assert q.category in ("business", "architecture", "constraints", "edge_cases")
            assert len(q.question) > 0
            assert len(q.why_asking) > 0


# ---------------------------------------------------------------------------
# Clarifier — generate_questions_via_scout (integration with mock)
# ---------------------------------------------------------------------------


class TestGenerateQuestionsViaScout:
    """Tests for the scout-based question generation with mocked router."""

    def test_successful_generation(self) -> None:
        """Should parse and return questions from scout model."""
        questions_json = json.dumps([
            {"category": "business", "question": "Why?", "why_asking": "reason"},
            {"category": "architecture", "question": "How?", "why_asking": "reason"},
        ])
        router = _make_router(scout_response=questions_json)

        questions = generate_questions_via_scout(router, "Add caching", {})
        assert len(questions) == 2
        assert questions[0].category == "business"

    def test_falls_back_on_router_failure(self) -> None:
        """Should return fallback questions when the router raises."""
        router = MagicMock()
        router.call_scout.side_effect = RuntimeError("Network error")

        questions = generate_questions_via_scout(router, "Add caching", {})
        assert len(questions) >= 3
        # Verify these are fallback questions (they have known patterns)
        assert all(isinstance(q, Question) for q in questions)

    def test_falls_back_on_empty_response(self) -> None:
        """Should return fallback questions when scout returns empty."""
        router = _make_router(scout_response="[]")

        questions = generate_questions_via_scout(router, "Add caching", {})
        # Empty scout response triggers ValueError in _generate_via_llm,
        # which triggers the fallback
        assert len(questions) >= 3

    def test_falls_back_on_invalid_json(self) -> None:
        """Should return fallback questions when scout returns invalid JSON."""
        router = _make_router(scout_response="This is not JSON at all")

        questions = generate_questions_via_scout(router, "Add caching", {})
        assert len(questions) >= 3

    def test_passes_context_in_prompt(self) -> None:
        """Should include context in the scout prompt."""
        questions_json = json.dumps([
            {"category": "business", "question": "?", "why_asking": "reason"},
        ])
        router = _make_router(scout_response=questions_json)

        generate_questions_via_scout(
            router,
            "Add caching",
            {"repo_map": "src/api.py\nsrc/cache.py"},
        )

        call_args = router.call_scout.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        prompt_text = messages[1]["content"]
        assert "repo_map" in prompt_text
        assert "src/api.py" in prompt_text

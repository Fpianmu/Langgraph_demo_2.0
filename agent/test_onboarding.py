from __future__ import annotations

from agent.onboarding import ONBOARDING_QUESTIONS, score_onboarding_answers


def test_onboarding_question_bank_has_twenty_six_questions() -> None:
    assert len(ONBOARDING_QUESTIONS) == 26


def test_onboarding_full_correct_answers_score_one_hundred() -> None:
    answers = [
        {"question_id": question["id"], "answer": question["answer"]}
        for question in ONBOARDING_QUESTIONS
    ]

    result = score_onboarding_answers(
        assessment_id="assessment_test_001",
        course_id="cnc_lathe",
        answers=answers,
    )

    assert result["overall_score"] == 100
    assert result["learner_level"] == "advanced"
    assert len(result["scored_items"]) == 26


def test_onboarding_background_answers_do_not_change_radar_score() -> None:
    answers = []
    for question in ONBOARDING_QUESTIONS:
        if question["capability_dimension"] == "background":
            answers.append({"question_id": question["id"], "answer": "A"})
        else:
            answers.append({"question_id": question["id"], "answer": question["answer"]})

    result = score_onboarding_answers(
        assessment_id="assessment_test_002",
        course_id="cnc_lathe",
        answers=answers,
    )

    assert result["overall_score"] == 100
    assert result["learner_level"] == "advanced"

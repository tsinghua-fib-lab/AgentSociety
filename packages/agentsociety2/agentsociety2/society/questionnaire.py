"""Questionnaire runtime for agent-facing external surveys."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from agentsociety2.agent import AgentBase
from agentsociety2.agent.json_utils import loads_llm_json
from agentsociety2.society.models import QuestionItem

__all__ = [
    "AgentQuestionnaireResult",
    "Questionnaire",
    "QuestionnaireAnswer",
    "QuestionnaireResponse",
    "QuestionnaireRunner",
]


class Questionnaire(BaseModel):
    """Runtime questionnaire definition."""

    questionnaire_id: str = Field(..., min_length=1)
    title: str = ""
    description: str = ""
    questions: list[QuestionItem] = Field(..., min_length=1)


class QuestionnaireAnswer(BaseModel):
    """Single parsed answer for one question."""

    question_id: str
    raw_text: str
    raw_response: str | None = None
    parsed_value: Any = None
    reason: str | None = None
    parse_success: bool = True
    parse_error: str | None = None


class AgentQuestionnaireResult(BaseModel):
    """Collected questionnaire answers for one agent."""

    agent_id: int
    agent_name: str
    answers: list[QuestionnaireAnswer]


class QuestionnaireResponse(BaseModel):
    """Top-level questionnaire execution result."""

    questionnaire_id: str
    title: str = ""
    description: str = ""
    simulation_time: str
    step_count: int
    target_agent_ids: list[int]
    questions: list[QuestionItem]
    responses: list[AgentQuestionnaireResult]
    context_snapshots: list[dict] = Field(default_factory=list)


def _build_question_prompt(
    questionnaire: Questionnaire,
    question: QuestionItem,
    *,
    t: datetime | None = None,
) -> str:
    lines = []
    if questionnaire.title:
        lines.append(f"Questionnaire Title: {questionnaire.title}")
    if questionnaire.description:
        lines.append(f"Questionnaire Description: {questionnaire.description}")
    lines.append(f"Question ID: {question.id}")
    lines.append(f"Question: {question.prompt}")
    lines.append("")
    lines.append(
        "Answer as yourself based on your own current beliefs, plans, emotions, and memory."
    )
    lines.append(
        "Return valid JSON with exactly two top-level fields in this order: "
        '"reason" and then "answer".'
    )
    lines.append(
        '"reason" should briefly decide the answer from your current state before '
        "writing the final answer."
    )
    lines.append(
        '"answer" must be your final decision after the reason; if the reason changes '
        "your mind, the answer field must match that final conclusion."
    )

    if question.response_type == "integer":
        lines.append('"answer" must be one integer.')
    elif question.response_type == "float":
        lines.append('"answer" must be one number.')
    elif question.response_type == "choice":
        options = ", ".join(question.choices)
        lines.append(f"Options: {options}")
        lines.append('"answer" must be one option exactly as written.')
    elif question.response_type == "json":
        lines.append(
            '"answer" must itself be valid JSON that directly answers the question.'
        )
    else:
        lines.append('"answer" must be concise plain text.')

    return "\n".join(lines).strip()


def _coerce_reason(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    stringified = str(value).strip()
    return stringified or None


def _stringify_answer_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value).strip()


def _parse_question_answer(
    question: QuestionItem, raw_text: str
) -> QuestionnaireAnswer:
    full_response = (raw_text or "").strip()
    answer_payload: Any = full_response
    answer_text = full_response
    reason: str | None = None
    structured_payload: Any = None

    try:
        structured_payload = loads_llm_json(full_response, expect="any")
    except ValueError:
        structured_payload = None

    if isinstance(structured_payload, dict) and "answer" in structured_payload:
        answer_payload = structured_payload.get("answer")
        answer_text = _stringify_answer_value(answer_payload)
        reason = _coerce_reason(structured_payload.get("reason"))

    parsed_value: Any = answer_text
    parse_success = True
    parse_error: str | None = None

    try:
        if question.response_type == "integer":
            if isinstance(answer_payload, bool):
                raise ValueError("boolean is not a valid integer answer")
            if isinstance(answer_payload, int):
                parsed_value = answer_payload
            elif isinstance(answer_payload, float) and answer_payload.is_integer():
                parsed_value = int(answer_payload)
            else:
                match = re.search(r"-?\d+", answer_text)
                if match is None:
                    raise ValueError("no integer found")
                parsed_value = int(match.group(0))
        elif question.response_type == "float":
            if isinstance(answer_payload, bool):
                raise ValueError("boolean is not a valid numeric answer")
            if isinstance(answer_payload, (int, float)):
                parsed_value = float(answer_payload)
            else:
                match = re.search(r"-?\d+(?:\.\d+)?", answer_text)
                if match is None:
                    raise ValueError("no number found")
                parsed_value = float(match.group(0))
        elif question.response_type == "choice":
            if not answer_text or len(answer_text) > 80:
                raise ValueError("empty or oversized choice answer")
            if any(
                bad in answer_text
                for bad in ('{"', "def ", "import ", "codegen", "await ", "\n    ")
            ):
                raise ValueError("answer looks like code, not a choice label")
            normalized = answer_text.casefold()
            exact = next(
                (
                    choice
                    for choice in question.choices
                    if choice.casefold() == normalized
                ),
                None,
            )
            if exact is None and len(normalized) >= 3:
                matches = [
                    choice
                    for choice in question.choices
                    if choice.casefold() in normalized
                    or normalized in choice.casefold()
                ]
                if len(matches) == 1:
                    exact = matches[0]
            if exact is None:
                raise ValueError(
                    f"answer does not match any choice: {question.choices}"
                )
            parsed_value = exact
        elif question.response_type == "json":
            if isinstance(structured_payload, dict) and "answer" in structured_payload:
                if isinstance(answer_payload, str):
                    parsed_value = loads_llm_json(answer_payload, expect="any")
                else:
                    parsed_value = answer_payload
            else:
                parsed_value = loads_llm_json(answer_text, expect="any")
        else:
            parsed_value = answer_text
    except Exception as exc:
        parse_success = False
        parse_error = str(exc)
        parsed_value = answer_text

    return QuestionnaireAnswer(
        question_id=question.id,
        raw_text=answer_text,
        raw_response=full_response,
        parsed_value=parsed_value,
        reason=reason,
        parse_success=parse_success,
        parse_error=parse_error,
    )


class QuestionnaireRunner:
    """Execute a questionnaire against selected agents."""

    async def run(
        self,
        questionnaire: Questionnaire,
        agents: Sequence[AgentBase],
        *,
        t: datetime,
        step_count: int,
        target_agent_ids: list[int] | None = None,
    ) -> QuestionnaireResponse:
        by_id = {agent.id: agent for agent in agents}
        if target_agent_ids is None:
            selected_agents = list(agents)
            target_ids = [agent.id for agent in selected_agents]
        else:
            missing = [
                agent_id for agent_id in target_agent_ids if agent_id not in by_id
            ]
            if missing:
                raise ValueError(f"Unknown target_agent_ids: {missing}")
            selected_agents = [by_id[agent_id] for agent_id in target_agent_ids]
            target_ids = list(target_agent_ids)

        answers_by_agent: dict[int, list[QuestionnaireAnswer]] = {
            agent.id: [] for agent in selected_agents
        }

        intention_q = "intention" in questionnaire.questionnaire_id

        for question in questionnaire.questions:
            prompt = _build_question_prompt(questionnaire, question, t=t)
            # 初次询问：所有 agent 并行（_ask_agents 内部 asyncio.gather，结果保序）。
            raw_answers = await self._ask_agents(
                agents=selected_agents,
                prompt=prompt,
                t=t,
            )
            answers = [_parse_question_answer(question, raw) for raw in raw_answers]
            # 收集解析失败的 choice 题目，整体并行重试，而不是逐个 await。
            needs_retry = intention_q and question.response_type == "choice"
            retry_indices = [
                idx
                for idx, answer in enumerate(answers)
                if needs_retry and not answer.parse_success
            ]
            if retry_indices:
                retry_prompt = (
                    prompt + "\n\nINVALID PREVIOUS ANSWER. Return JSON only with "
                    '"answer" as exactly one listed option (copy verbatim) and a short "reason".'
                )
                retry_agents = [selected_agents[idx] for idx in retry_indices]
                retry_raws = await self._ask_agents(
                    agents=retry_agents,
                    prompt=retry_prompt,
                    t=t,
                )
                for idx, retry_raw in zip(retry_indices, retry_raws, strict=False):
                    answers[idx] = _parse_question_answer(question, retry_raw)
            for agent, answer in zip(selected_agents, answers, strict=False):
                answers_by_agent[agent.id].append(answer)

        return QuestionnaireResponse(
            questionnaire_id=questionnaire.questionnaire_id,
            title=questionnaire.title,
            description=questionnaire.description,
            simulation_time=t.isoformat(),
            step_count=step_count,
            target_agent_ids=target_ids,
            questions=questionnaire.questions,
            responses=[
                AgentQuestionnaireResult(
                    agent_id=agent.id,
                    agent_name=agent.name,
                    answers=answers_by_agent[agent.id],
                )
                for agent in selected_agents
            ],
        )

    async def _ask_agents(
        self,
        *,
        agents: Sequence[AgentBase],
        prompt: str,
        t: datetime,
    ) -> list[str]:
        """Ask every agent the same prompt through the standard ``ask`` interface.

        Each agent runs its own reasoning loop and returns its answer text as a
        string; the caller parses that text into a structured answer. The request
        is readonly so answering never mutates environment or workspace state.
        ``t`` is the authoritative simulation time so agents reason as of now.
        """
        coroutines = [agent.ask(prompt, readonly=True, t=t) for agent in agents]
        return list(await asyncio.gather(*coroutines))

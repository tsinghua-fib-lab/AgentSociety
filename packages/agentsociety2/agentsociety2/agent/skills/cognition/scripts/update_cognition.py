#!/usr/bin/env python3
"""Deterministic appraisal baseline for emotion and intention state."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EMOTION_KEYS = ("sadness", "joy", "fear", "disgust", "anger", "surprise")


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def clamp10(value: float) -> int:
    return int(round(max(0.0, min(10.0, value))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--tick", type=int, default=None)
    parser.add_argument("--args-json", default="{}")
    return parser.parse_args()


def runtime_args(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise TypeError("--args-json must decode to an object")
    return payload


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def keyword_score(text: str, patterns: list[str]) -> float:
    if not text:
        return 0.0
    hits = sum(1 for p in patterns if re.search(p, text, flags=re.I))
    return clamp(hits / max(1, len(patterns)))


def previous_intensities(previous: dict[str, Any]) -> dict[str, int]:
    raw = previous.get("intensities") if isinstance(previous, dict) else None
    if not isinstance(raw, dict):
        return {k: 3 for k in EMOTION_KEYS}
    return {k: clamp10(float(raw.get(k, 3))) for k in EMOTION_KEYS}


def apply_continuity(
    prev: dict[str, int], target: dict[str, float], max_delta: int = 2
) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in EMOTION_KEYS:
        old = prev.get(key, 3)
        wanted = target.get(key, old)
        out[key] = clamp10(max(old - max_delta, min(old + max_delta, wanted)))
    return out


def build_appraisal(
    observation: str,
    needs: dict[str, Any],
    norms: dict[str, Any],
    affordances: dict[str, Any],
    economy: dict[str, Any],
    previous_emotion: dict[str, Any],
) -> dict[str, float]:
    text = observation.lower()
    need_map = needs.get("needs", {}) if isinstance(needs.get("needs"), dict) else {}
    urgency = clamp(float(needs.get("urgency", 0.0) or 0.0))
    safety_satisfaction = clamp(float(need_map.get("safety", 0.7) or 0.7))
    social_satisfaction = clamp(float(need_map.get("social", 0.7) or 0.7))

    threat = max(
        keyword_score(
            text,
            [
                "danger",
                "threat",
                "unsafe",
                "attack",
                "accident",
                "risk",
                "紧急",
                "危险",
                "威胁",
            ],
        ),
        1.0 - safety_satisfaction,
    )
    obstacle = keyword_score(
        text,
        [
            "blocked",
            "fail",
            "late",
            "cannot",
            "closed",
            "refused",
            "阻碍",
            "失败",
            "迟到",
        ],
    )
    reward = keyword_score(
        text,
        [
            "success",
            "helped",
            "good",
            "accepted",
            "paid",
            "finished",
            "成功",
            "顺利",
            "被帮助",
        ],
    )
    novelty = keyword_score(
        text,
        [
            "new",
            "unexpected",
            "surprise",
            "suddenly",
            "unknown",
            "突然",
            "意外",
            "陌生",
        ],
    )
    conflict = keyword_score(
        text, ["conflict", "argue", "angry", "insult", "betray", "争吵", "冲突", "羞辱"]
    )

    active_norms = (
        norms.get("active_norms", [])
        if isinstance(norms.get("active_norms"), list)
        else []
    )
    norm_pressure = max(
        [
            float(n.get("pressure", 0.0) or 0.0)
            for n in active_norms
            if isinstance(n, dict)
        ]
        + [0.0]
    )
    violation_risk = max(
        [
            float(n.get("violation_risk", 0.0) or 0.0)
            for n in active_norms
            if isinstance(n, dict)
        ]
        + [0.0]
    )

    perceived_control = float(affordances.get("perceived_control_hint", 0.65) or 0.65)
    if affordances.get("blocked_actions"):
        perceived_control -= 0.15
    if float(economy.get("scarcity_pressure", 0.0) or 0.0) > 0.6:
        perceived_control -= 0.1

    prev_valence = (
        float(previous_emotion.get("valence", 0.0) or 0.0)
        if isinstance(previous_emotion, dict)
        else 0.0
    )
    pleasantness = clamp(
        0.5
        + 0.35 * reward
        - 0.3 * obstacle
        - 0.3 * threat
        - 0.15 * conflict
        + 0.1 * prev_valence
    )

    return {
        "novelty": novelty,
        "pleasantness": pleasantness,
        "goal_conduciveness": clamp(
            0.5 + 0.35 * reward - 0.35 * obstacle - 0.2 * urgency
        ),
        "urgency": urgency,
        "threat": threat,
        "social_disconnection": 1.0 - social_satisfaction,
        "conflict": conflict,
        "norm_pressure": clamp(norm_pressure),
        "norm_violation_risk": clamp(violation_risk),
        "perceived_control": clamp(perceived_control),
    }


def derive_emotion(
    appraisal: dict[str, float], previous: dict[str, Any]
) -> dict[str, Any]:
    prev = previous_intensities(previous)
    target = {
        "joy": 2
        + 6 * appraisal["pleasantness"]
        + 1.5 * appraisal["goal_conduciveness"],
        "fear": 2
        + 6 * appraisal["threat"]
        + 1.5 * appraisal["urgency"]
        - 1.5 * appraisal["perceived_control"],
        "anger": 2
        + 5 * appraisal["conflict"]
        + 3 * (1 - appraisal["goal_conduciveness"])
        - appraisal["perceived_control"],
        "sadness": 2
        + 4 * (1 - appraisal["pleasantness"])
        + 2 * appraisal["social_disconnection"],
        "disgust": 1
        + 3 * appraisal["norm_violation_risk"]
        + 2 * keyword_score(str(appraisal), ["contamination"]),
        "surprise": 1 + 7 * appraisal["novelty"],
    }
    intensities = apply_continuity(prev, target)

    valence = clamp(
        (
            intensities["joy"]
            - max(intensities["sadness"], intensities["anger"], intensities["fear"])
        )
        / 10,
        -1,
        1,
    )
    arousal = clamp(
        (
            intensities["fear"]
            + intensities["anger"]
            + intensities["surprise"]
            + appraisal["urgency"] * 10
        )
        / 40
    )

    primary = "Hope"
    strongest = max(EMOTION_KEYS, key=lambda k: intensities[k])
    if intensities["fear"] >= 6 or (strongest == "fear" and valence < 0):
        primary = "Fear"
    elif intensities["anger"] >= 6 or (strongest == "anger" and valence < 0):
        primary = "Anger"
    elif intensities["sadness"] >= 6 or (strongest == "sadness" and valence < 0):
        primary = "Distress"
    elif intensities["joy"] >= 6 or (strongest == "joy" and valence >= 0):
        primary = "Satisfaction"
    elif intensities["surprise"] >= 6:
        primary = "Surprise"

    prev_mood = (
        previous.get("mood", {}) if isinstance(previous.get("mood"), dict) else {}
    )
    mood_valence = 0.85 * float(prev_mood.get("valence", 0.0) or 0.0) + 0.15 * valence
    mood_arousal = 0.85 * float(prev_mood.get("arousal", 0.5) or 0.5) + 0.15 * arousal

    return {
        "_meta": {
            "skill": "cognition",
            "purpose": "Current appraised emotion and mood state.",
            "model": "Scherer-style appraisal baseline with bounded emotion continuity",
        },
        "_summary": f"{primary} with valence {valence:.2f} and arousal {arousal:.2f}.",
        "primary": primary,
        "valence": round(valence, 3),
        "arousal": round(arousal, 3),
        "mood": {
            "valence": round(clamp(mood_valence, -1, 1), 3),
            "arousal": round(clamp(mood_arousal), 3),
            "stability": float(prev_mood.get("stability", 0.7) or 0.7),
        },
        "intensities": intensities,
        "appraisal": {k: round(v, 3) for k, v in appraisal.items()},
        "note": "Deterministic appraisal baseline; LLM may refine context-specific labels.",
    }


def choose_intention(
    emotion: dict[str, Any],
    needs: dict[str, Any],
    norms: dict[str, Any],
    affordances: dict[str, Any],
) -> dict[str, Any]:
    current_need = str(needs.get("current_need", "") or "").strip()
    urgency = clamp(float(needs.get("urgency", 0.0) or 0.0))
    perceived_control_hint = clamp(
        float(affordances.get("perceived_control_hint", 0.65) or 0.65)
    )
    norm_pressure = max(
        [
            float(n.get("pressure", 0.0) or 0.0)
            for n in norms.get("active_norms", [])
            if isinstance(n, dict)
        ]
        + [0.0]
    )

    feasible = affordances.get("feasible_actions", [])
    feasible_text = (
        ", ".join(feasible[:3])
        if isinstance(feasible, list) and feasible
        else "available low-risk action"
    )

    if current_need in {"eat", "drink", "sleep", "rest", "safety"} and urgency > 0.45:
        label = f"Address urgent need: {current_need}"
        attitude = 0.65 + 0.3 * urgency
    elif norm_pressure > 0.65:
        label = "Comply with the most salient social norm"
        attitude = 0.65
    elif emotion.get("primary") == "Fear":
        label = "Move toward safety and reduce uncertainty"
        attitude = 0.75
    elif emotion.get("primary") == "Anger":
        label = "Resolve the immediate conflict without escalating"
        attitude = 0.62
    else:
        label = f"Continue with {feasible_text}"
        attitude = 0.58

    joy = emotion.get("intensities", {}).get("joy", 3)
    fear = emotion.get("intensities", {}).get("fear", 3)
    anger = emotion.get("intensities", {}).get("anger", 3)
    control = perceived_control_hint
    applied: list[str] = []
    if joy > 7:
        attitude += 0.05
        control += 0.03
        applied.append("high joy increased willingness")
    if fear > 6:
        control -= 0.1
        applied.append("high fear lowered perceived control")
    if anger > 6:
        control -= 0.05
        applied.append("high anger lowered planning control")

    subjective_norm = clamp(0.35 + 0.6 * norm_pressure)
    attitude = clamp(attitude)
    control = clamp(control)
    final_score = attitude + subjective_norm + control

    return {
        "_meta": {
            "skill": "cognition",
            "purpose": "Current top-level intention selected from appraisal, needs, norms, and affordances.",
            "model": "Theory of Planned Behavior scoring baseline",
        },
        "_summary": label,
        "intention": label,
        "priority": 1,
        "attitude": round(attitude, 3),
        "subjective_norm": round(subjective_norm, 3),
        "perceived_control": round(control, 3),
        "final_score": round(final_score, 3),
        "emotion_influence": {
            "applied_modifiers": applied,
        },
        "reasoning": "Deterministic TPB baseline; cognition may refine the wording from richer context.",
    }


def main() -> int:
    args = parse_args()
    payload = runtime_args(args.args_json)
    state = Path(str(payload.get("state_dir", args.state_dir)))
    tick = args.tick if args.tick is not None else payload.get("tick")
    tick = int(tick) if tick is not None else None
    state.mkdir(parents=True, exist_ok=True)

    observation = read_text(state / "observation.txt")
    needs = read_json(state / "needs.json", {})
    norms = read_json(state / "norms.json", {})
    affordances = read_json(state / "affordances.json", {})
    economy = read_json(state / "economy.json", {})
    previous_emotion = read_json(state / "emotion.json", {})

    appraisal = build_appraisal(
        observation, needs, norms, affordances, economy, previous_emotion
    )
    emotion = derive_emotion(appraisal, previous_emotion)
    if tick is not None:
        emotion["tick"] = tick

    intention = choose_intention(emotion, needs, norms, affordances)
    if tick is not None:
        intention["tick"] = tick

    (state / "emotion.json").write_text(
        json.dumps(emotion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (state / "intention.json").write_text(
        json.dumps(intention, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "ok": True,
                "primary": emotion["primary"],
                "intention": intention["intention"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

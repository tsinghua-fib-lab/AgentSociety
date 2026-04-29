---
name: cognition
description: Produce emotion.json and intention.json from workspace context.
script: scripts/update_cognition.py
---

# Cognition

Read available workspace context and produce `state/emotion.json` and `state/intention.json`.

Research basis: `references/research_basis.md`.

## Internal Logic (One Sentence)

Appraise the current tick for novelty, pleasantness, goal conduciveness, urgency, controllability, norm pressure, and need pressure, then write bounded emotion/mood state to `state/emotion.json` and the highest-scoring TPB intention to `state/intention.json`.

## Output Files

- `state/emotion.json`: Current emotional state (includes mood layer)
- `state/intention.json`: Current intention/goal

## Input Files (optional, read if present)

Read any existing files from the workspace as context. Common inputs include:

| File | Use |
|------|-----|
| `state/observation.txt` | Main grounding for this tick |
| `state/thought.txt` | Inner monologue context |
| `state/needs.json`, `state/current_need.txt` | Urgency context |
| `state/memory.jsonl` | Last 5–10 lines for continuity |
| `state/emotion.json`, `state/intention.json` | Prior state for continuity |
| `state/plan_state.json` | Whether a multi-step plan is in flight |

Also use **Agent Identity** from the system prompt. Other JSON in the workspace (`state/beliefs.json`, etc.) can be read if present. **Skip missing files gracefully.**

## What to do

1. Integrate whatever inputs exist into one appraisal.
2. Write `state/emotion.json`: `primary`, `mood`, dimensional `intensities`, plus `valence` / `arousal` / `note`.
3. Write `state/intention.json`: one chosen goal with TPB scores.

If deterministic baseline is preferred, run `scripts/update_cognition.py` first, then optionally refine labels, reasoning, and candidate goals with LLM context.

```bash
python skills/cognition/scripts/update_cognition.py --state-dir state --tick 120
```

The script uses Scherer-style appraisal checks and TPB scoring. It is intentionally conservative: it clamps emotion changes per tick and records appraisal values for debugging.

## Emotion Layers

Emotions operate on three timescales (based on psychological research):

### Layer 1: Emotion (seconds to minutes)

Short-term, event-driven responses.

- Dimensions: `sadness`, `joy`, `fear`, `disgust`, `anger`, `surprise` (0–10)
- Changes rapidly based on immediate events
- Maximum change: ±2 per tick per dimension

### Layer 2: Mood (hours to days)

Medium-term, cumulative emotional state.

- Persists across multiple ticks
- Influences emotion recovery speed
- Drifts slowly toward neutral
- Represented in `state/emotion.json` as `mood` object

| Mood Field | Range | Description |
|------------|-------|-------------|
| `valence` | -1 to 1 | Positive/negative tendency |
| `arousal` | 0 to 1 | Energy level |
| `stability` | 0 to 1 | How resistant to change |

### Layer 3: Personality (long-term)

Stable traits from `state/personality.json` (if exists).

| Trait | Effect |
|-------|--------|
| High `neuroticism` (> 0.7) | Amplify all emotions × 1.3 |
| Low `neuroticism` (< 0.3) | Dampen emotion changes, cap at ±1 per tick |
| High `extraversion` (> 0.7) | Amplify positive emotions (joy, surprise) × 1.2 |
| High `agreeableness` (> 0.7) | Reduce anger responses −2 |

## Emotion Continuity Rules

**CRITICAL**: These rules must be followed strictly.

1. **Maximum change per tick**: Each intensity dimension can change by at most ±2 per tick
2. **Inertia**: If no significant events occurred, intensities should stay within ±1 of previous values
3. **Valence drift**: Emotions slowly drift toward neutral (intensity 3-4) without reinforcing events
4. **Mood influence**: Current mood affects how quickly emotions recover:
   - Positive mood (valence > 0.3): Joy recovers +1 per tick
   - Negative mood (valence < -0.3): Sadness/anger recovers slower
   - Low stability: Faster emotion swings

### Validation Checklist

Before writing `state/emotion.json`, verify:

- [ ] No dimension changed by more than ±2 from previous values
- [ ] Changes are justified by events in observation/memory
- [ ] Mood is updated based on cumulative emotion history

## Need-Emotion Linkage

Low need satisfaction affects emotional state:

| Need Condition | Emotion Effect |
|----------------|----------------|
| satiety < 0.3 | anger +2, joy −1 (hangry) |
| energy < 0.3 | sadness +1, joy −1 (fatigued) |
| safety < 0.3 | fear +2, surprise +1 (anxious) |
| social < 0.3 | sadness +1, loneliness amplifies |

### Intensities (0–10 integers)

Dimensions: `sadness`, `joy`, `fear`, `disgust`, `anger`, `surprise`

| Band | Level |
|------|-------|
| 0–2 | very low |
| 3–4 | low |
| 5–6 | moderate |
| 7–8 | high |
| 9–10 | very high |

- Combine recent events (`state/memory.jsonl` tail, `state/observation.txt`) with any urgency signals present in the workspace (e.g., need levels if available).
- If a previous `state/emotion.json` exists, change intensities only when the situation meaningfully shifted; otherwise stay near prior values.

### Primary Emotion Label

Exactly **one** English label, case-sensitive, from:

`Joy`, `Distress`, `Resentment`, `Pity`, `Hope`, `Fear`, `Satisfaction`, `Relief`, `Disappointment`, `Pride`, `Admiration`, `Shame`, `Reproach`, `Liking`, `Disliking`, `Gratitude`, `Anger`, `Gratification`, `Remorse`, `Love`, `Hate`, `Surprise`

## Intention (Theory of Planned Behavior)

| Field | Range | Meaning |
|-------|-------|---------|
| `attitude` | 0–1 | How much you favor doing it |
| `subjective_norm` | 0–1 | Social pressure / what others expect |
| `perceived_control` | 0–1 | How controllable / feasible it feels |

Higher values on all three → stronger commitment. `priority`: lower number = more urgent this tick.

## Emotion-Intention Integration

**CRITICAL**: Current emotional state directly influences intention selection via TPB modifiers.

### Emotion Modifiers

Apply these modifiers to the base TPB scores based on current emotion intensities:

| Emotion Condition | attitude Modifier | perceived_control Modifier | Effect |
|-------------------|-------------------|---------------------------|--------|
| `joy > 7` | +0.10 | +0.05 | Optimism bias, more willing to act |
| `joy < 3` | -0.05 | -0.05 | Reduced motivation |
| `anger > 6` | -0.10 | -0.05 | Impulsive, less careful planning |
| `fear > 6` | +0.05 (for safety goals) | -0.10 | Risk-averse, lower confidence |
| `fear > 6` | -0.10 (for risky goals) | -0.10 | Avoids risky intentions |
| `sadness > 6` | -0.05 | -0.05 | Withdrawn, lower energy |
| `surprise > 7` | +0.05 | -0.05 | Open to new options, but uncertain |

### Computation Formula

```
final_attitude = base_attitude × (1 + emotion_attitude_modifier)
final_perceived_control = base_perceived_control × (1 + emotion_control_modifier)

final_score = final_attitude + subjective_norm + final_perceived_control
```

**Clamping**: All final values must be clamped to [0, 1] range.

### Emotion-Behavior Tendencies

Emotions also create natural behavioral tendencies that should bias candidate selection:

| Primary Emotion | Preferred Intention Types | Avoided Intention Types |
|-----------------|--------------------------|------------------------|
| Joy | Social, exploration, leisure | Safety-seeking, withdrawal |
| Anger | Confrontation, goal pursuit | Passive waiting, avoidance |
| Fear | Safety-seeking, risk avoidance | Bold actions, exploration |
| Sadness | Withdrawal, reflection | Social engagement, active goals |
| Hope | Goal pursuit, planning | Giving up, passive resignation |
| Satisfaction | Rest, leisure, social | Urgent action, new challenges |

### Selection Procedure

1. List up to 5 candidate goals (fewer is fine).
2. If the workspace contains urgency signals (e.g., unmet needs), prefer candidates that address them; otherwise leisure or exploration is appropriate.
3. Score each candidate with the three TPB fields (base values).
4. **Apply emotion modifiers** to attitude and perceived_control based on current emotion state.
5. **Consider emotion-behavior tendencies** when ranking candidates.
6. Assign `priority` to each candidate based on final_score.
7. Emit only the best candidate as `state/intention.json` (highest final_score, or lowest `priority`).
8. Phrase `intention` as a goal ("Eat lunch at the café"), not step-by-step motor instructions.

### Example Calculation

```
Current emotion: anger=7, joy=3, fear=2

Candidate: "Confront Alice about the issue"
Base scores: attitude=0.7, subjective_norm=0.5, perceived_control=0.6

Emotion modifiers:
- anger > 6 → attitude -0.10, perceived_control -0.05
- joy < 3 → attitude -0.05, perceived_control -0.05

Final scores:
- attitude = 0.7 × (1 - 0.10 - 0.05) = 0.7 × 0.85 = 0.595
- perceived_control = 0.6 × (1 - 0.05 - 0.05) = 0.6 × 0.90 = 0.54
- final_score = 0.595 + 0.5 + 0.54 = 1.635
```

## Output File Schemas

### state/emotion.json

```json
{
  "_meta": {
    "skill": "cognition",
    "purpose": "Current appraised emotion and mood state."
  },
  "_summary": "Hope with valence 0.5 and arousal 0.4.",
  "primary": "Hope",
  "valence": 0.5,
  "arousal": 0.4,
  "mood": {
    "valence": 0.2,
    "arousal": 0.5,
    "stability": 0.7
  },
  "intensities": {
    "sadness": 3,
    "joy": 6,
    "fear": 2,
    "disgust": 1,
    "anger": 1,
    "surprise": 3
  },
  "appraisal": {
    "novelty": 0.1,
    "pleasantness": 0.65,
    "goal_conduciveness": 0.7,
    "urgency": 0.2,
    "perceived_control": 0.8,
    "norm_pressure": 0.4
  },
  "note": "Brief first-person gloss"
}
```

### state/intention.json

```json
{
  "_meta": {
    "skill": "cognition",
    "purpose": "Current top-level intention selected from appraisal, needs, norms, and affordances."
  },
  "_summary": "Have lunch at the café",
  "intention": "Have lunch at the café",
  "priority": 1,
  "attitude": 0.9,
  "subjective_norm": 0.7,
  "perceived_control": 0.8,
  "final_score": 2.4,
  "emotion_influence": {
    "joy_modifier": 0.05,
    "applied_modifiers": ["joy > 7: +0.10 attitude"]
  },
  "reasoning": "One or two sentences"
}
```

**Note**: The `emotion_influence` field records how emotions affected this decision, providing transparency and debuggability.

## Execution Sequence

1. `workspace_read` any of the optional inputs that exist (skip missing paths).
2. Compute mood update (drift toward neutral, influenced by recent emotions).
3. Compute emotion intensities (respect continuity rules).
4. `workspace_write("state/emotion.json", ...)`
5. **List candidate intentions and apply emotion modifiers** to compute final scores.
6. `workspace_write("state/intention.json", ...)` (include emotion_influence field)
7. `done`

## Notes

- Intentions should be feasible given the latest observation; if the situation is unclear, prefer low-risk intentions (`wait`, `observe`, `move to safer area`) over fantasy.

## Plan Completion/Failure Emotion Updates

When a plan completes or fails, emotions should be updated accordingly:

### Plan Completed Successfully

| Emotion | Change |
|---------|--------|
| joy | +2 to +4 (depending on plan importance) |
| pride | +2 to +3 |
| fear | −1 (reduced anxiety) |
| sadness | −1 |

**Primary emotion**: `Satisfaction`, `Pride`, or `Gratification`

### Plan Failed

| Emotion | Change |
|---------|--------|
| sadness | +2 to +3 |
| anger | +1 to +2 (if external cause) |
| fear | +1 (increased uncertainty) |
| joy | −2 |

**Primary emotion**: `Disappointment`, `Frustration`, or `Remorse` (if self-caused)

### Integration with Plan Skill

The `plan` skill may signal completion/failure via `state/plan_state.json`. When detected:
1. Read the plan target and outcome
2. Apply appropriate emotion adjustments
3. Update `state/emotion.json` with new intensities
4. Write a brief note in the `note` field explaining the change

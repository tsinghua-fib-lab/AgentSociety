# Cognition Modeling Basis

## Why this matters

Intentions in social settings are rarely pure utility maximization. They are influenced by attitudes, social pressure, perceived control, and current affective state.

## Evidence anchors

- Theory of Planned Behavior (Ajzen): intention is shaped by attitude, subjective norm, and perceived behavioral control.
- Meta-analytic support: TPB predicts many social/health behaviors with moderate effect sizes.
- Emotion-cognition interaction literature: affect shifts risk perception, confidence, and action tendency.
- Scherer Component Process Model (CPM): emotion differentiation can be modeled as repeated appraisal checks over relevance, implications, coping potential, and normative significance.

## Simulation translation

### Appraisal state

Use bounded appraisal variables in `[0, 1]`:

| Variable | Meaning | Typical inputs |
|----------|---------|----------------|
| `novelty` | unexpectedness / unfamiliarity | observation keywords, new agents, sudden events |
| `pleasantness` | intrinsic positive/negative tone | success, help, comfort, threat, conflict |
| `goal_conduciveness` | whether the event helps current goals | plan state, obstacles, success/failure |
| `urgency` | need for immediate response | needs, danger, deadlines |
| `perceived_control` | controllability / coping potential | affordances, money, health, blocked actions |
| `norm_pressure` | external standards and sanctions | norms, witnesses, role obligations |
| `norm_violation_risk` | risk of shame/guilt/sanction | forbidden actions, moral emotion risk |

### Emotion update

The script maps appraisal to six intensity dimensions:

```text
fear    ~= threat + urgency - perceived_control
anger   ~= conflict + blocked goal - perceived_control
sadness ~= unpleasantness + social disconnection
joy     ~= pleasantness + goal conduciveness
surprise ~= novelty
disgust ~= norm violation / contamination cues
```

Then it applies continuity:

```text
emotion_next = clamp(previous +/- max_delta_per_tick)
```

This prevents single-tick emotional jumps unless the LLM has strong contextual evidence to override the baseline.

### Intention scoring

For each candidate intention:

- base_attitude in [0, 1]
- subjective_norm in [0, 1]
- perceived_control in [0, 1]
- apply emotion modifiers to attitude/control
- final_score = weighted sum

Then output only top candidate with brief reasoning.

## Practical notes

- Preserve continuity: do not allow huge emotion swings without a major event.
- Separate immediate emotion and slower mood components.
- Let hard constraints from affordance/economy lower perceived_control.

## References

- Ajzen, I. (1991). The theory of planned behavior. *Organizational Behavior and Human Decision Processes*.
- Scherer, K. R. (2001). Appraisal considered as a process of multilevel sequential checking. In *Appraisal Processes in Emotion*.
- Ortony, A., Clore, G. L., & Collins, A. (1988). *The Cognitive Structure of Emotions*.

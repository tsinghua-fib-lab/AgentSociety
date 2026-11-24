from datetime import date, datetime, time
from types import SimpleNamespace

from agentsociety2.society.models import QuestionItem
from agentsociety2.society.questionnaire import Questionnaire, _build_question_prompt
from daily_mobility.intentions import (
    INTENTION_CHOICES,
    build_primary_intention_prompt,
    build_questionnaire_runtime_hints,
    coerce_duplicate_meal_intention,
    current_meal_window,
    daily_mobility_intention_slot_index,
    in_standard_meal_window,
    is_daily_mobility_intention_questionnaire,
    meals_completed_today,
    normalize_questionnaire_intention,
    postprocess_questionnaire_intention_answers,
)
from daily_mobility.mobility_snapshot import commute_target_aoi


def _simulation_time(hour: int, minute: int = 0) -> datetime:
    """Use the benchmark's local clock on its fixed test day."""
    return datetime.combine(date(2000, 1, 3), time(hour, minute))


def test_slot_index_from_questionnaire_id():
    assert daily_mobility_intention_slot_index("daily_mobility_intention_slot_0") == 0
    assert daily_mobility_intention_slot_index("daily_mobility_intention_slot_47") == 47
    assert daily_mobility_intention_slot_index("other_survey") is None


def test_meal_window_helpers():
    assert current_meal_window(8.0) == "breakfast"
    assert current_meal_window(10.0) is None
    assert in_standard_meal_window(12.0) is True
    assert in_standard_meal_window(15.0) is False


def test_is_daily_mobility_intention_questionnaire():
    assert is_daily_mobility_intention_questionnaire("daily_mobility_intention_slot_3")
    assert not is_daily_mobility_intention_questionnaire("health_check")


def test_build_primary_intention_prompt_describes_slot_and_choices():
    prompt = build_primary_intention_prompt(11)
    assert "time slot 12 of 48" in prompt
    assert "30" in prompt
    assert "dominant" in prompt.casefold()
    assert "current" in prompt.casefold()
    for choice in INTENTION_CHOICES:
        assert choice in prompt
    # The agent reasons through its ReAct loop and postprocess applies the
    # benchmark guards, so the prompt must not hard-code clock/meal rules.
    assert "09:00" not in prompt
    assert "State first" not in prompt


def test_build_question_prompt_uses_questionnaire_prompt_without_framework_override():
    questionnaire = Questionnaire(
        questionnaire_id="daily_mobility_intention_slot_5",
        title="Daily mobility intention (15 min)",
        questions=[
            QuestionItem(
                id="primary_intention",
                prompt="OLD YAML PROMPT SHOULD NOT APPEAR",
                response_type="choice",
                choices=list(INTENTION_CHOICES),
            )
        ],
    )
    question = questionnaire.questions[0]
    built = _build_question_prompt(questionnaire, question)
    assert "OLD YAML PROMPT SHOULD NOT APPEAR" in built
    assert "time slot 6 of 48" not in built
    assert "rare" not in built.casefold()
    assert '"reason" and then "answer"' in built
    assert '"answer" must be your final decision after the reason' in built


def test_work_hours_hint_when_still_at_home():
    t = _simulation_time(10)
    ctx = {
        "state/observation_ctx.json": {
            "observations": {
                "MobilitySpace.get_person": {
                    "position": {"aoi_id": 500063853},
                    "status": "idle",
                }
            }
        },
        "profile": "home AOI 500063853 work AOI 500026935",
    }
    hints = build_questionnaire_runtime_hints(sim_time=t, workspace_context=ctx)
    joined = " ".join(hints)
    assert "still at HOME" in joined
    assert "500063853" in joined


def test_morning_hungry_prioritizes_breakfast_without_hard_ban():
    t = _simulation_time(7, 30)
    ctx = {
        "state/needs.json": {"needs": {"hunger": 0.65, "energy": 0.85, "stress": 0.05}},
        "profile": "home AOI 1 work AOI 2",
        "memory": "commuting toward work workplace",
    }
    hints = build_questionnaire_runtime_hints(sim_time=t, workspace_context=ctx)
    joined = " ".join(hints)
    assert "eating out" in joined
    assert "breakfast can be the main activity" in joined
    assert "breakfast" in joined.lower()


def test_hints_use_hunger_energy_stress_schema():
    t = _simulation_time(22)
    ctx = {
        "state/needs.json": {"needs": {"hunger": 0.70, "energy": 0.25, "stress": 0.80}},
        "profile": "home AOI 1 work AOI 2",
    }
    hints = build_questionnaire_runtime_hints(sim_time=t, workspace_context=ctx)
    joined = " ".join(hints)
    assert "energy=0.25" in joined
    assert "stress=0.80" in joined
    assert "hunger=0.70" in joined
    assert "satiety" not in joined
    assert "fatigue" not in joined


def test_hints_block_duplicate_meal_window():
    t = _simulation_time(12, 30)
    ctx = {
        "state/needs.json": {"needs": {"hunger": 0.67, "energy": 0.70, "stress": 0.20}},
        "state/meal_state.json": {
            "last_meal_window": "lunch",
            "restored_windows": {"2000-01-03:lunch": "2000-01-03T12:00:00"},
        },
        "profile": "home AOI 1 work AOI 2",
    }
    hints = build_questionnaire_runtime_hints(sim_time=t, workspace_context=ctx)
    joined = " ".join(hints)
    assert "lunch is already recorded" in joined
    assert "do NOT choose eating out again" in joined


def test_hints_block_repeat_lunch_after_actual_meal():
    t = _simulation_time(13)
    ctx = {
        "state/needs.json": {"needs": {"hunger": 0.7, "energy": 0.7, "stress": 0.1}},
        "state/meal_state.json": {
            "last_meal_window": "lunch",
            "last_meal_time": "2000-01-03T12:00:00",
            "last_meal_poi_id": 700008843,
            "restored_windows": {"2000-01-03:lunch": "2000-01-03T12:00:00"},
        },
    }
    hints = build_questionnaire_runtime_hints(sim_time=t, workspace_context=ctx)
    joined = " ".join(hints)
    assert "do NOT choose eating out again" in joined
    assert "lunch" in joined


def test_questionnaire_label_alone_not_counted_as_meal_done():
    meal_state = {
        "questionnaire_meals": {"lunch": "2000-01-03T12:00:00"},
    }
    assert meals_completed_today(meal_state, day=date(2000, 1, 3)) == set()


def test_normalize_night_work_at_home_to_sleep_or_home():
    t = _simulation_time(3)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t,
            energy=0.8,
            current_aoi=1,
            home_aoi=1,
            work_aoi=2,
        )
        == "sleep"
    )
    t6 = _simulation_time(6)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t6,
            energy=0.4,
            current_aoi=1,
            home_aoi=1,
            work_aoi=2,
        )
        == "sleep"
    )


def test_normalize_work_before_nine_at_home():
    t9 = _simulation_time(9, 30)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t9,
            energy=0.7,
            current_aoi=2,
            home_aoi=1,
            work_aoi=2,
        )
        == "work"
    )
    t8 = _simulation_time(8)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t8,
            energy=0.7,
            current_aoi=1,
            home_aoi=1,
            work_aoi=2,
        )
        == "home activity"
    )


def test_normalize_strong_rhythm_work_requires_commute_or_workplace():
    t = _simulation_time(9, 30)
    assert (
        normalize_questionnaire_intention(
            "home activity",
            sim_time=t,
            hunger=0.30,
            energy=0.70,
            current_aoi=1,
            home_aoi=1,
            work_aoi=2,
            rhythm_recommendation="work",
            scheduled_activity="work",
            norm_strength=0.80,
            mobility_status="idle",
        )
        == "home activity"
    )
    assert (
        normalize_questionnaire_intention(
            "home activity",
            sim_time=t,
            hunger=0.30,
            energy=0.70,
            current_aoi=1,
            home_aoi=1,
            work_aoi=2,
            rhythm_recommendation="work",
            scheduled_activity="work",
            norm_strength=0.80,
            mobility_status="moving",
        )
        == "work"
    )
    assert (
        normalize_questionnaire_intention(
            "home activity",
            sim_time=t,
            hunger=0.30,
            energy=0.70,
            current_aoi=2,
            home_aoi=1,
            work_aoi=2,
            rhythm_recommendation="work",
            scheduled_activity="work",
            norm_strength=0.80,
            mobility_status="idle",
        )
        == "work"
    )


def test_normalize_hungry_lunch_window_to_eating_out():
    t = _simulation_time(12)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t,
            hunger=0.65,
            energy=0.6,
            current_aoi=2,
            home_aoi=1,
            work_aoi=2,
        )
        == "eating out"
    )


def test_coerce_duplicate_lunch_to_work():
    t = _simulation_time(13)
    meal_state = {
        "last_meal_window": "lunch",
        "last_meal_time": "2000-01-03T12:00:00",
        "last_meal_poi_id": 1,
        "restored_windows": {"2000-01-03:lunch": "2000-01-03T12:00:00"},
    }
    assert coerce_duplicate_meal_intention("eating out", t, meal_state) == "work"


def test_hints_lunch_while_moving_prefers_eating_out():
    t = _simulation_time(12)
    ctx = {
        "state/needs.json": {"needs": {"hunger": 0.72, "energy": 0.7, "stress": 0.1}},
        "state/observation_ctx.json": {
            "observations": {
                "MobilitySpace.get_person": {
                    "position": {"aoi_id": None},
                    "status": "moving",
                }
            }
        },
    }
    hints = build_questionnaire_runtime_hints(sim_time=t, workspace_context=ctx)
    joined = " ".join(hints)
    assert "choose eating out" in joined
    assert "Do NOT label the whole slot as work" in joined


def test_postprocess_questionnaire_intention_answers_preserves_agent_output():
    """Postprocess must NOT rewrite the agent's answer with benchmark rules."""
    import json

    class Runtime:
        def __init__(self):
            self.writes: dict[str, str] = {}

        def workspace_write(self, path, content):
            self.writes[path] = content

    class Agent:
        def __init__(self):
            self._skill_runtime = Runtime()
            self._files = {"state/meal_state.json": {}}

        def _read_workspace_json(self, path):
            return self._files.get(path)

        def _write_meal_state(self, data):
            self._files["state/meal_state.json"] = data

    answer = SimpleNamespace(
        question_id="primary_intention",
        parse_success=True,
        parsed_value="work",
        reason="test",
    )
    result = SimpleNamespace(
        step_count=30,
        responses=[SimpleNamespace(agent_id=1, answers=[answer])],
        context_snapshots=[],
    )
    agent = Agent()
    postprocess_questionnaire_intention_answers(
        result,
        sim_time=_simulation_time(15),
        agents_by_id={1: agent},
    )
    # Agent output is final: "work" stays "work" even though the agent is at home
    # — the LLM capability is evaluated as-is, with no rule-code guard applied.
    assert answer.parsed_value == "work"
    restore = json.loads(agent._skill_runtime.writes["_restore_intention.json"])
    assert restore["goal"] == "work"
    assert restore["source"] == "questionnaire"


def test_normalize_work_at_food_poi_not_workplace():
    t = _simulation_time(18)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t,
            hunger=0.20,
            energy=0.60,
            current_aoi=99,
            home_aoi=1,
            work_aoi=2,
            poi_id=700000001,
            poi_category="restaurant",
        )
        == "home activity"
    )
    t_dinner = _simulation_time(18, 30)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t_dinner,
            hunger=0.50,
            energy=0.60,
            current_aoi=99,
            home_aoi=1,
            work_aoi=2,
            poi_id=700000001,
            poi_category="restaurant",
        )
        == "eating out"
    )


def test_slot_index_for_time():
    from daily_mobility.intentions import slot_index_for_time

    t = _simulation_time(17, 30)
    assert slot_index_for_time(t) == 35


def test_normalize_breakfast_when_hungry_morning():
    t = _simulation_time(7, 30)
    assert (
        normalize_questionnaire_intention(
            "home activity",
            sim_time=t,
            hunger=0.65,
            energy=0.55,
            current_aoi=50001,
            home_aoi=50001,
            work_aoi=50002,
        )
        == "eating out"
    )


def test_normalize_breakfast_not_hungry_enough_stays_home():
    t = _simulation_time(7, 30)
    assert (
        normalize_questionnaire_intention(
            "home activity",
            sim_time=t,
            hunger=0.50,
            energy=0.55,
            current_aoi=50001,
            home_aoi=50001,
            work_aoi=50002,
        )
        == "home activity"
    )


def test_meals_completed_ignores_hunger_suffix_keys():
    meal_state = {
        "restored_windows": {
            "2000-01-03:lunch": "2000-01-03T12:00:00",
            "2000-01-03:lunch:hunger": "2000-01-03T12:00:00",
        }
    }
    done = meals_completed_today(meal_state, day=date(2000, 1, 3))
    assert done == {"lunch"}


def test_normalize_dinner_at_work_promotes_eating_out():
    t = _simulation_time(18)
    assert (
        normalize_questionnaire_intention(
            "home activity",
            sim_time=t,
            hunger=0.62,
            energy=0.5,
            current_aoi=50002,
            home_aoi=50001,
            work_aoi=50002,
        )
        == "eating out"
    )


def test_normalize_lunch_uses_meal_threshold_not_breakfast_threshold():
    t = _simulation_time(12)
    assert (
        normalize_questionnaire_intention(
            "work",
            sim_time=t,
            hunger=0.50,
            energy=0.55,
            current_aoi=50002,
            home_aoi=50001,
            work_aoi=50002,
        )
        == "eating out"
    )


def test_hunger_after_meal_fixed_targets():
    from daily_mobility.intentions import (
        HUNGER_AFTER_BREAKFAST,
        HUNGER_AFTER_DINNER,
        HUNGER_AFTER_LUNCH,
        hunger_after_meal,
    )

    assert hunger_after_meal("breakfast", 0.72) == HUNGER_AFTER_BREAKFAST
    assert hunger_after_meal("lunch", 0.72) == HUNGER_AFTER_LUNCH
    assert hunger_after_meal("dinner", 0.72) == HUNGER_AFTER_DINNER


def test_finalize_timeline_moving_is_commute_and_single_meal_slot(tmp_path):
    from daily_mobility.tools.live_data import (
        finalize_timeline_intentions,
    )

    parsed: dict[str, list] = {
        "intentions": ["eating out"] * 48,
        "times": [
            f"2000-01-03T{(i // 2):02d}:{30 if i % 2 else 0:02d}:00" for i in range(48)
        ],
        "statuses": ["idle"] * 48,
        "position_kinds": ["home"] * 48,
        "base_intentions": ["home activity"] * 48,
    }
    parsed["statuses"][10] = "moving"
    parsed["position_kinds"][10] = "moving"
    agent_dir = tmp_path / "agents" / "agent_0001" / "state"
    agent_dir.mkdir(parents=True)
    (agent_dir / "meal_state.json").write_text(
        '{"restored_windows": {"2000-01-03:breakfast": "2000-01-03T07:30:00"}}',
        encoding="utf-8",
    )
    finalize_timeline_intentions(tmp_path, 1, parsed)
    assert parsed["intentions"][10] == "commute"
    assert parsed["intentions"][15] == "eating out"
    assert parsed["intentions"][16] == "home activity"


def test_apply_end_of_slot_positions_copies_next_snapshot():
    from daily_mobility.tools.live_data import (
        POSITION_FIELD_KEYS,
        align_intentions_with_positions,
        apply_end_of_slot_positions,
    )

    parsed: dict[str, list] = {k: [None] * 48 for k in POSITION_FIELD_KEYS}
    parsed["intentions"] = [None] * 48
    parsed["times"] = [None] * 48
    parsed["home_aois"] = [None] * 48
    parsed["work_aois"] = [None] * 48
    parsed["lngs"][15] = 116.0
    parsed["lngs"][16] = 116.1
    parsed["aoi_ids"][15] = 100
    parsed["aoi_ids"][16] = 200
    parsed["poi_categories"][15] = None
    parsed["poi_categories"][16] = None
    parsed["poi_ids"][15] = None
    parsed["poi_ids"][16] = 7001
    parsed["home_aois"][15] = 100
    parsed["home_aois"][16] = 100
    parsed["work_aois"][15] = 300
    parsed["work_aois"][16] = 300
    parsed["intentions"][15] = "work"
    parsed["intentions"][16] = "work"
    apply_end_of_slot_positions(parsed)
    assert parsed["aoi_ids"][15] == 200
    align_intentions_with_positions(parsed)
    assert parsed["intentions"][15] == "work"


def test_commute_target_aoi_morning_and_evening():
    assert (
        commute_target_aoi(
            hour=9.0,
            home_aoi=1,
            work_aoi=2,
            current_aoi=1,
            status="idle",
        )
        == 2
    )
    assert (
        commute_target_aoi(
            hour=17.0,
            home_aoi=1,
            work_aoi=2,
            current_aoi=2,
            status="idle",
        )
        is None
    )
    assert (
        commute_target_aoi(
            hour=20.0,
            home_aoi=1,
            work_aoi=2,
            current_aoi=2,
            status="idle",
        )
        is None
    )
    assert (
        commute_target_aoi(
            hour=21.5,
            home_aoi=1,
            work_aoi=2,
            current_aoi=2,
            status="idle",
        )
        == 1
    )
    assert (
        commute_target_aoi(
            hour=10.0,
            home_aoi=1,
            work_aoi=2,
            current_aoi=2,
            status="idle",
        )
        is None
    )
    assert (
        commute_target_aoi(
            hour=22.0,
            home_aoi=1,
            work_aoi=2,
            current_aoi=2,
            status="idle",
        )
        == 1
    )

"""
Implicit Association Test (IAT) Experiment Environment
Environment for Implicit Association Test experiment based on AgentSociety2
"""

import asyncio
import json
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool
from agentsociety2.env.base import dump_int_map, load_int_map
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"


# Response models for tool functions
class TrialInfo(BaseModel):
    """Response model for get_next_trial() function"""

    trial_id: int = Field(..., description="Trial ID (sequential number)")
    block_code: str = Field(
        ...,
        description="Block code (identity_practice, valence_practice, congruent, identity_switch, incongruent)",
    )
    stimuli: str = Field(..., description="Stimulus word (in Chinese)")
    identity: str | None = Field(
        None,
        description="Identity category (1=self, 2=others, or None if not applicable)",
    )
    valence: str | None = Field(
        None,
        description="Valence category (1=positive, 2=negative, or None if not applicable)",
    )
    left_label: str = Field(..., description="Left label")
    right_label: str = Field(..., description="Right label")
    correct_key: str = Field(..., description="Correct response key (z or m)")
    instruction: str = Field(..., description="Instruction for this trial")


class SubmitTrialResponse(BaseModel):
    """Response model for submit_trial_response() function"""

    agent_id: int = Field(..., description="Agent ID")
    trial_id: int = Field(..., description="Trial ID")
    key_press: str = Field(..., description="Pressed key (z or m)")
    rt: float = Field(..., description="Response time in seconds")
    corr: int = Field(..., description="Correctness (1=correct, 0=incorrect)")
    status: str = Field(..., description="Status: 'submitted' or 'completed'")


class ImplicitAssociationTestEnv(EnvBase):
    """Environment for Implicit Association Test (IAT) experiment based on AgentSociety2"""

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("completed_trials", "INTEGER", nullable=False),
        ColumnDef("total_trials", "INTEGER", nullable=False),
        ColumnDef("progress_percent", "REAL", nullable=False),
        ColumnDef("accuracy", "REAL", nullable=False),
        ColumnDef("average_rt", "REAL", nullable=False),
        ColumnDef("responses", "JSON", nullable=False),
    ]

    # Standard IAT trial sequence
    # This is a simplified version - in practice, trials should be loaded from data files
    # or generated according to IAT protocol
    STANDARD_TRIALS: ClassVar[list[dict]] = [
        # Block 1: Identity Practice (12 trials)
        {
            "block_code": "identity_practice",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "本人",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "他",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "我的",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "别人",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "自个",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "她",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "俺",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "identity_practice",
            "stimuli": "他的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        # Block 2: Valence Practice (12 trials)
        {
            "block_code": "valence_practice",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "友好",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "冷漠",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "诚实",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "自私",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "慷慨",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "卑鄙",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "真诚",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "valence_practice",
            "stimuli": "狡猾",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        # Block 3: Congruent (self+positive, others+negative) - 48 trials
        # Mix of identity and valence words
        {
            "block_code": "congruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "others",
            "right_label": "self",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "m",
        },
        {
            "block_code": "congruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        {
            "block_code": "congruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "negative",
            "right_label": "positive",
            "correct_key": "z",
        },
        # Block 4: Identity Switch (12 trials)
        {
            "block_code": "identity_switch",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "本人",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "他",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "我的",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "别人",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "自个",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "她",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "俺",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "identity_switch",
            "stimuli": "他的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        # Block 5: Incongruent (self+negative, others+positive) - 48 trials
        {
            "block_code": "incongruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "他们",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "虚伪",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "可靠",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "自我",
            "identity": "1",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "她的",
            "identity": "2",
            "valence": None,
            "left_label": "self",
            "right_label": "others",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "吝啬",
            "identity": None,
            "valence": "2",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "m",
        },
        {
            "block_code": "incongruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
        {
            "block_code": "incongruent",
            "stimuli": "善良",
            "identity": None,
            "valence": "1",
            "left_label": "positive",
            "right_label": "negative",
            "correct_key": "z",
        },
    ]

    def __init__(self, agent_ids: list[int], trials: list[dict] | None = None):
        """
        Initialize the Implicit Association Test environment.

        :param agent_ids: List of agent IDs participating in the experiment
        :param trials: Optional custom trial sequence. If None, uses STANDARD_TRIALS
        """
        super().__init__()

        self.agent_ids = agent_ids
        self.num_agents = len(agent_ids)

        # Use custom trials or standard trials
        self.trials = trials if trials is not None else self.STANDARD_TRIALS
        self.total_trials = len(self.trials)

        # Track progress for each agent: {agent_id: current_trial_index}
        self._trial_progress: dict[int, int] = {agent_id: 0 for agent_id in agent_ids}

        # Store responses: {agent_id: [{trial_id, key_press, rt, corr, ...}]}
        self._responses: dict[int, list[dict]] = {
            agent_id: [] for agent_id in agent_ids
        }

        self._lock = asyncio.Lock()
        self._step_counter: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。"""
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "trial_progress": dump_int_map(self._trial_progress),
                    "responses": dump_int_map(self._responses),
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。``trials`` 是构造配置，不存盘。"""
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        d = json.loads(state_path.read_text(encoding="utf-8"))
        self._trial_progress = {
            aid: int(v) for aid, v in load_int_map(d.get("trial_progress")).items()
        }
        self._responses = {
            aid: list(v) for aid, v in load_int_map(d.get("responses")).items()
        }
        self._step_counter = int(d.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions and JSON schemas for data models.
        """
        description = f"""{cls.__name__}: Implicit Association Test (IAT) experiment environment module.

**Description:** Manages an IAT experiment where agents perform implicit association tests to measure implicit self-esteem through reaction times and accuracy.

**Initialization Parameters (excluding llm):**
- agent_ids (List[int]): List of agent IDs participating in the experiment
- trials (Optional[List[Dict]]): Optional custom trial sequence

**Example initialization config:**
```json
{{
  "agent_ids": [101, 102, 103]
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return (
            "Implicit Association Test environment for measuring implicit associations."
        )

    def _get_instruction(
        self, block_code: str, identity: str | None, valence: str | None
    ) -> str:
        """Generate instruction text for a trial"""
        if block_code == "identity_practice":
            return "Categorize the word as 'self' (press m) or 'others' (press z)"
        elif block_code == "valence_practice":
            return "Categorize the word as 'positive' (press m) or 'negative' (press z)"
        elif block_code == "congruent":
            if identity:
                return "Categorize the identity word: 'self' (press m) or 'others' (press z)"
            else:
                return "Categorize the valence word: 'positive' (press m) or 'negative' (press z)"
        elif block_code == "identity_switch":
            return "Categorize the word as 'self' (press z) or 'others' (press m) - NOTE: labels are reversed!"
        elif block_code == "incongruent":
            if identity:
                return "Categorize the identity word: 'self' (press z) or 'others' (press m) - NOTE: labels are reversed!"
            else:
                return "Categorize the valence word: 'positive' (press z) or 'negative' (press m) - NOTE: labels are reversed!"
        return "Categorize the word according to the labels"

    @tool(readonly=True, kind="observe")
    async def get_next_trial(self, agent_id: int) -> TrialInfo:
        """
        Get the next trial information for an agent.

        :param agent_id: The agent's ID

        :returns: TrialInfo containing trial details
        """
        async with self._lock:
            if agent_id not in self.agent_ids:
                raise ValueError(
                    f"Agent ID {agent_id} is not in the experiment. Valid IDs: {self.agent_ids}"
                )

            current_index = self._trial_progress[agent_id]

            if current_index >= self.total_trials:
                raise ValueError(
                    f"Agent {agent_id} has completed all {self.total_trials} trials. No more trials available."
                )

            trial_data = self.trials[current_index]
            instruction = self._get_instruction(
                trial_data["block_code"],
                trial_data.get("identity"),
                trial_data.get("valence"),
            )

            return TrialInfo(
                trial_id=current_index + 1,  # 1-indexed
                block_code=trial_data["block_code"],
                stimuli=trial_data["stimuli"],
                identity=trial_data.get("identity"),
                valence=trial_data.get("valence"),
                left_label=trial_data["left_label"],
                right_label=trial_data["right_label"],
                correct_key=trial_data["correct_key"],
                instruction=instruction,
            )

    @tool(readonly=False)
    async def submit_trial_response(
        self, agent_id: int, trial_id: int, key_press: str, rt: float
    ) -> SubmitTrialResponse:
        """
        Submit response for a trial.

        :param agent_id: The agent's ID
        :param trial_id: The trial ID (from get_next_trial)
        :param key_press: The pressed key ("z" or "m")
        :param rt: Response time in seconds

        :returns: SubmitTrialResponse containing correctness and status
        """
        async with self._lock:
            # Validate agent_id
            if agent_id not in self.agent_ids:
                raise ValueError(
                    f"Agent ID {agent_id} is not in the experiment. Valid IDs: {self.agent_ids}"
                )

            # Validate trial_id
            expected_index = trial_id - 1  # Convert to 0-indexed
            if expected_index != self._trial_progress[agent_id]:
                raise ValueError(
                    f"Trial ID mismatch. Expected trial {self._trial_progress[agent_id] + 1}, got {trial_id}. "
                    f"Please call get_next_trial() first."
                )

            if expected_index >= self.total_trials:
                raise ValueError(
                    f"Trial ID {trial_id} is out of range. Total trials: {self.total_trials}"
                )

            # Validate key_press
            key_press = key_press.lower().strip()
            if key_press not in ["z", "m"]:
                raise ValueError(f"Invalid key_press '{key_press}'. Must be 'z' or 'm'")

            # Validate rt (should be positive and reasonable)
            if rt < 0:
                rt = 0.0
            rt = min(rt, 10.0)

            # Get trial data
            trial_data = self.trials[expected_index]
            correct_key = trial_data["correct_key"].lower()

            # Check correctness
            corr = 1 if key_press == correct_key else 0

            # Store response
            response_data = {
                "trial_id": trial_id,
                "block_code": trial_data["block_code"],
                "stimuli": trial_data["stimuli"],
                "identity": trial_data.get("identity"),
                "valence": trial_data.get("valence"),
                "left_label": trial_data["left_label"],
                "right_label": trial_data["right_label"],
                "correct_key": correct_key,
                "key_press": key_press,
                "rt": rt,
                "corr": corr,
            }
            self._responses[agent_id].append(response_data)

            # Update progress
            self._trial_progress[agent_id] += 1

            # Check if completed
            all_completed = self._trial_progress[agent_id] >= self.total_trials
            status = "completed" if all_completed else "submitted"

            return SubmitTrialResponse(
                agent_id=agent_id,
                trial_id=trial_id,
                key_press=key_press,
                rt=rt,
                corr=corr,
                status=status,
            )

    @tool(readonly=True, kind="observe")
    async def get_my_progress(self, agent_id: int) -> dict:
        """
        Get progress for a specific agent.

        :param agent_id: The agent's ID

        :returns: Dictionary containing progress information
        """
        async with self._lock:
            if agent_id not in self.agent_ids:
                raise ValueError(
                    f"Agent ID {agent_id} is not in the experiment. Valid IDs: {self.agent_ids}"
                )

            completed = self._trial_progress[agent_id]
            responses = self._responses[agent_id]

            # Calculate accuracy
            if responses:
                correct_count = sum(1 for r in responses if r["corr"] == 1)
                accuracy = correct_count / len(responses)
                avg_rt = sum(r["rt"] for r in responses) / len(responses)
            else:
                accuracy = 0.0
                avg_rt = 0.0

            return {
                "agent_id": agent_id,
                "completed_trials": completed,
                "total_trials": self.total_trials,
                "progress_percent": (completed / self.total_trials * 100)
                if self.total_trials > 0
                else 0,
                "accuracy": accuracy,
                "average_rt": avg_rt,
            }

    @tool(readonly=True, kind="statistics")
    async def get_all_progress(self) -> dict[int, dict]:
        """
        Get progress for all agents.

        :returns: Dictionary mapping agent_id to progress information
        """
        async with self._lock:
            result = {}
            for agent_id in self.agent_ids:
                # Use the same logic as get_my_progress
                completed = self._trial_progress[agent_id]
                responses = self._responses[agent_id]

                if responses:
                    correct_count = sum(1 for r in responses if r["corr"] == 1)
                    accuracy = correct_count / len(responses)
                    avg_rt = sum(r["rt"] for r in responses) / len(responses)
                else:
                    accuracy = 0.0
                    avg_rt = 0.0

                result[agent_id] = {
                    "completed_trials": completed,
                    "total_trials": self.total_trials,
                    "progress_percent": (completed / self.total_trials * 100)
                    if self.total_trials > 0
                    else 0,
                    "accuracy": accuracy,
                    "average_rt": avg_rt,
                }
            return result

    async def init(self, start_datetime: datetime):
        """
        Initialize the environment module.
        """
        await super().init(start_datetime)
        async with self._lock:
            self._trial_progress = {agent_id: 0 for agent_id in self.agent_ids}
            self._responses = {agent_id: [] for agent_id in self.agent_ids}
            self._step_counter = 0

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks (1 tick = 1 second) of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.current_datetime = t
            records = []
            for agent_id in self.agent_ids:
                responses = self._responses[agent_id]
                completed_trials = self._trial_progress[agent_id]
                if responses:
                    correct_count = sum(
                        1 for response in responses if response["corr"] == 1
                    )
                    accuracy = correct_count / len(responses)
                    average_rt = sum(response["rt"] for response in responses) / len(
                        responses
                    )
                else:
                    accuracy = 0.0
                    average_rt = 0.0

                records.append(
                    {
                        "agent_id": agent_id,
                        "completed_trials": completed_trials,
                        "total_trials": self.total_trials,
                        "progress_percent": (
                            completed_trials / self.total_trials * 100
                            if self.total_trials > 0
                            else 0.0
                        ),
                        "accuracy": accuracy,
                        "average_rt": average_rt,
                        "responses": [response.copy() for response in responses],
                    }
                )

        await self._write_agent_state_batch(
            step=self._step_counter,
            t=t,
            records=records,
        )
        self._step_counter += 1

    def get_results(self) -> dict[int, list[dict]]:
        """
        Get all trial responses (synchronous method for result extraction).

        :returns: Dictionary mapping agent_id to list of response dictionaries
        """
        return {
            agent_id: [response.copy() for response in responses]
            for agent_id, responses in self._responses.items()
        }


__all__ = ["ImplicitAssociationTestEnv", "SubmitTrialResponse", "TrialInfo"]

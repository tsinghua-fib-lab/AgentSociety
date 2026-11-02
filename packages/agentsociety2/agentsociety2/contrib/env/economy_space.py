import asyncio
import json
from datetime import datetime, timedelta
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import (
    EnvBase,
    tool,
)
from agentsociety2.env.base import load_int_map
from agentsociety2.logger import get_logger
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

# 本模块自选的 workspace 布局：<workspace_root>/state/ENV_STATE.json。
_STATE_REL = "state/ENV_STATE.json"


class EconomyPerson(BaseModel):
    id: int = Field(..., description="Person ID")
    currency: float = Field(..., description="The currency of the person")
    skill: str = Field(..., description="The skill description of the person")
    consumption: float = Field(
        ..., description="The consumption of the person (per day)"
    )
    income: float = Field(..., description="The income of the person (per day)")

    def __str__(self):
        """Convert the data into a string to describe it for LLM"""
        return f"Person {self.id}'s currency is {self.currency}, will consume {self.consumption} per day, and has an income of {self.income} per day. He has a skill: {self.skill}."


class TaxBracket(BaseModel):
    """The tax bracket of the government"""

    cutoff: float = Field(..., description="The cutoff point of the tax bracket")
    rate: float = Field(..., description="The rate of the tax bracket")

    def __str__(self):
        """Convert the data into a string to describe it for LLM"""
        return f"Tax bracket with cutoff {self.cutoff} and rate {self.rate}."


# Response models for tool functions
class GetPersonResponse(BaseModel):
    """Response model for get_person() function"""

    person: dict = Field(..., description="The person data")


class GetPersonCurrencyResponse(BaseModel):
    """Response model for get_person_currency() function"""

    currency: float = Field(..., description="The currency of the person")


class AddPersonCurrencyResponse(BaseModel):
    """Response model for add_person_currency() function"""

    old_currency: float = Field(..., description="The old currency value")
    new_currency: float = Field(..., description="The new currency value")
    delta: float = Field(..., description="The currency delta")


class GetPersonSkillResponse(BaseModel):
    """Response model for get_person_skill() function"""

    skill: str = Field(..., description="The skill of the person")


class GetPersonConsumptionResponse(BaseModel):
    """Response model for get_person_consumption() function"""

    consumption: float = Field(..., description="The consumption of the person")


class SetPersonConsumptionResponse(BaseModel):
    """Response model for set_person_consumption() function"""

    old_consumption: float = Field(..., description="The old consumption value")
    new_consumption: float = Field(..., description="The new consumption value")


class GetPersonIncomeResponse(BaseModel):
    """Response model for get_person_income() function"""

    income: float = Field(..., description="The income of the person")


class SetPersonIncomeResponse(BaseModel):
    """Response model for set_person_income() function"""

    old_income: float = Field(..., description="The old income value")
    new_income: float = Field(..., description="The new income value")


class EconomySpace(EnvBase):
    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    # 声明式状态持久化
    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("currency", "REAL"),
        ColumnDef("income", "REAL"),
        ColumnDef("consumption", "REAL"),
    ]
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("bank_interest_rate", "REAL"),
    ]

    def __init__(self, persons: list[EconomyPerson] | list[dict], **kwargs):
        """
        Initialize the Economy Space environment.

        :param persons: List of persons to initialize the environment with. Can be EconomyPerson objects or dicts.
        """
        if kwargs:
            unknown_keys = list(kwargs.keys())
            get_logger().warning(
                f"EconomySpace received unknown initialization kwargs: {unknown_keys}. "
                "These will be ignored."
            )
        super().__init__()

        # Convert dict to EconomyPerson if needed
        person_objects = []
        for p in persons:
            if isinstance(p, dict):
                person_objects.append(EconomyPerson.model_validate(p))
            else:
                person_objects.append(p)
        self._persons: dict[int, EconomyPerson] = {p.id: p for p in person_objects}
        """The persons in the economy space"""
        self._bank_interest_rate: float = 0.01
        """BANK: The interest rate of the bank"""
        self._last_run_datetime: datetime = datetime.now()
        """BANK: The last tick of the bank interest rate"""
        self._gov_tax_brackets: list[TaxBracket] = [
            TaxBracket(cutoff=0 / 365, rate=0.1),
            TaxBracket(cutoff=9875 / 365, rate=0.12),
            TaxBracket(cutoff=40125 / 365, rate=0.22),
            TaxBracket(cutoff=85525 / 365, rate=0.24),
            TaxBracket(cutoff=163300 / 365, rate=0.32),
            TaxBracket(cutoff=207350 / 365, rate=0.35),
            TaxBracket(cutoff=518400 / 365, rate=0.37),
        ]
        """GOVERNMENT: The tax brackets of the government"""
        self._lock = asyncio.Lock()
        self._step_counter: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。

        嵌套 pydantic（``EconomyPerson``/``TaxBracket``）用 model_dump；
        ``_last_run_datetime`` 用 isoformat；``_lock`` 不存盘。
        """
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "persons": {
                        str(pid): p.model_dump(mode="json")
                        for pid, p in self._persons.items()
                    },
                    "bank_interest_rate": self._bank_interest_rate,
                    "last_run_datetime": (
                        self._last_run_datetime.isoformat()
                        if self._last_run_datetime is not None
                        else None
                    ),
                    "gov_tax_brackets": [
                        b.model_dump(mode="json") for b in self._gov_tax_brackets
                    ],
                    "step_counter": self._step_counter,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。

        晚于 ``init()`` （会重置 ``_last_run_datetime``）执行；仅在 checkpoint 含
        ``last_run_datetime`` 时覆盖，缺失则保留 init() 的 start_datetime
        （绝不注入墙钟，避免日切判断错乱）。``_lock`` 由 ``__init__`` 重建。
        """
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self._persons = {
            pid: EconomyPerson.model_validate(p)
            for pid, p in load_int_map(state.get("persons")).items()
        }
        self._bank_interest_rate = float(
            state.get("bank_interest_rate", self._bank_interest_rate)
        )
        last_run = state.get("last_run_datetime")
        if last_run:
            self._last_run_datetime = datetime.fromisoformat(last_run)
        self._gov_tax_brackets = [
            TaxBracket.model_validate(b) for b in state.get("gov_tax_brackets", [])
        ]
        self._step_counter = int(state.get("step_counter", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions and JSON schemas for data models.
        """

        # Get JSON schema for EconomyPerson
        person_schema = EconomyPerson.model_json_schema()

        description = f"""{cls.__name__}: Economy management environment module for economic simulation.

**Description:** Manages economic simulation with person financial data, currency transactions, income/consumption tracking, banking, and taxation systems.

**Initialization Parameters (excluding llm):**
- persons (List[EconomyPerson] | List[dict]): List of persons to initialize the environment with. Can be EconomyPerson objects or dicts matching the schema.

**EconomyPerson JSON Schema:**
```json
{json.dumps(person_schema, indent=2)}
```

**Example initialization config:**
```json
{{
  "persons": [
    {{
      "id": 1,
      "currency": 1000.0,
      "skill": "Software Engineer",
      "consumption": 50.0,
      "income": 200.0
    }}
  ]
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Economy environment for managing agents' currency, income, consumption, and skills."

    @tool(readonly=True, kind="observe")
    async def get_person(self, id: int) -> EconomyPerson:
        """
        Get the person by id.

        :param id: The id of the person

        :returns: The person by id
        """
        async with self._lock:
            if id not in self._persons:
                raise ValueError(f"Person {id} not found")
            return self._persons[id]

    @tool(readonly=True)
    async def get_person_currency(self, id: int) -> GetPersonCurrencyResponse:
        """
        Get the currency of a person.

        :param id: The id of the person

        :returns: The context containing the currency of the person
        """
        async with self._lock:
            if id not in self._persons:
                return GetPersonCurrencyResponse(currency=0.0)
            person = self._persons[id]
            return GetPersonCurrencyResponse(currency=person.currency)

    @tool(readonly=False)
    async def add_person_currency(
        self, id: int, delta: float
    ) -> AddPersonCurrencyResponse:
        """
        Add the currency of a person.

        :param id: The id of the person
        :param delta: The delta of the currency

        :returns: The context of the person
        """
        async with self._lock:
            if id not in self._persons:
                return AddPersonCurrencyResponse(
                    old_currency=0.0, new_currency=0.0, delta=delta
                )
            person = self._persons[id]
            old_currency = person.currency
            person.currency += delta
            return AddPersonCurrencyResponse(
                old_currency=old_currency,
                new_currency=person.currency,
                delta=delta,
            )

    @tool(readonly=True)
    async def get_person_skill(self, id: int) -> GetPersonSkillResponse:
        """
        Get the skill of a person.

        :param id: The id of the person

        :returns: The context containing the skill of the person
        """
        async with self._lock:
            if id not in self._persons:
                return GetPersonSkillResponse(skill="")
            person = self._persons[id]
            return GetPersonSkillResponse(skill=person.skill)

    @tool(readonly=True)
    async def get_person_consumption(self, id: int) -> GetPersonConsumptionResponse:
        """
        Get the consumption of a person.

        :param id: The id of the person

        :returns: The context containing the consumption of the person
        """
        async with self._lock:
            if id not in self._persons:
                return GetPersonConsumptionResponse(consumption=0.0)
            person = self._persons[id]
            return GetPersonConsumptionResponse(consumption=person.consumption)

    @tool(readonly=False)
    async def set_person_consumption(
        self, id: int, consumption: float
    ) -> SetPersonConsumptionResponse:
        """
        Set the consumption of a person.

        :param id: The id of the person
        :param consumption: The consumption of the person

        :returns: The context of the person
        """
        async with self._lock:
            if id not in self._persons:
                return SetPersonConsumptionResponse(
                    old_consumption=0.0, new_consumption=consumption
                )
            person = self._persons[id]
            old_consumption = person.consumption
            person.consumption = consumption
            return SetPersonConsumptionResponse(
                old_consumption=old_consumption,
                new_consumption=person.consumption,
            )

    @tool(readonly=True)
    async def get_person_income(self, id: int) -> GetPersonIncomeResponse:
        """
        Get the income of a person.

        :param id: The id of the person

        :returns: The context containing the income of the person
        """
        async with self._lock:
            if id not in self._persons:
                return GetPersonIncomeResponse(income=0.0)
            person = self._persons[id]
            return GetPersonIncomeResponse(income=person.income)

    @tool(readonly=False)
    async def set_person_income(
        self, id: int, income: float
    ) -> SetPersonIncomeResponse:
        """
        Set the income of a person.

        :param id: The id of the person
        :param income: The income of the person

        :returns: The context of the person
        """
        async with self._lock:
            if id not in self._persons:
                return SetPersonIncomeResponse(old_income=0.0, new_income=income)
            person = self._persons[id]
            old_income = person.income
            person.income = income
            return SetPersonIncomeResponse(
                old_income=old_income,
                new_income=person.income,
            )

    async def init(self, start_datetime: datetime):
        """
        Initialize the environment module.
        """
        await super().init(start_datetime)
        self._last_run_datetime = start_datetime

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks (1 tick = 1 second) of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        new_run_datetime = self._last_run_datetime
        for _ in range(tick):
            new_run_datetime += timedelta(seconds=1)
            # implement bank interest calculation
            if new_run_datetime - self._last_run_datetime >= timedelta(days=1):
                # give rate each day
                self._last_run_datetime = new_run_datetime
                for person in self._persons.values():
                    old_currency = person.currency
                    person.currency += person.currency * self._bank_interest_rate / 365
                    # calculate income and consumption
                    person.currency += person.income
                    # calculate tax
                    tax = 0
                    for bracket in self._gov_tax_brackets:
                        if person.income > bracket.cutoff:
                            tax += (person.income - bracket.cutoff) * bracket.rate
                    person.currency -= tax
                    # calculate consumption
                    person.currency -= person.consumption
                    get_logger().debug(
                        f"Person {person.id}'s currency: {old_currency} -> {person.currency} after one day."
                    )
        self.t = t

        # 持久化 agent 状态
        for person in self._persons.values():
            await self._write_agent_state(
                agent_id=person.id,
                step=self._step_counter,
                t=t,
                currency=person.currency,
                income=person.income,
                consumption=person.consumption,
            )
        # 持久化环境全局状态
        await self._write_env_state(
            step=self._step_counter,
            t=t,
            bank_interest_rate=self._bank_interest_rate,
        )
        self._step_counter += 1

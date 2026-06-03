import asyncio
import json
import warnings
from datetime import datetime, timedelta
from typing import ClassVar, List

from agentsociety2.env import (
    EnvBase,
    tool,
)
from agentsociety2.logger import get_logger
from agentsociety2.storage import ColumnDef
from pydantic import BaseModel, Field


class EconomyPerson(BaseModel):
    id: int = Field(..., description="Person ID")
    currency: float = Field(..., description="The currency of the person")
    skill: str = Field(..., description="The skill description of the person")
    consumption: float = Field(..., description="The consumption of the person (per day)")
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
    # 声明式状态持久化
    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("currency", "REAL"),
        ColumnDef("income", "REAL"),
        ColumnDef("consumption", "REAL"),
    ]
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("bank_interest_rate", "REAL"),
    ]

   def __init__(self, persons: List[EconomyPerson] | List[dict], **kwargs):
        """
        Initialize the Economy Space environment.

        :param persons: List of persons to initialize the environment with. Can be EconomyPerson objects or dicts.
        :param kwargs: Additional keyword arguments. Unknown arguments
                 will trigger a warning.
        """
        super().__init__()

       + # Warn about unsupported kwargs
  if kwargs:
      warnings.warn(
          f"EconomySpace received unknown keyword arguments"
          f" that will be ignored: {list(kwargs.keys())}. "
          f"Please check your init_config.json for unsupported"
          f" parameters under the economy environment config.",
          UserWarning,
          stacklevel=2,
      )

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

    @classmethod
    def mcp_description(cls) -> str:
        """
        Return a description text for MCP environment module candidate list.
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

    @property
    def description(self):
        """Description of the environment module for router selection and function calling"""
        return """You are an economy management environment module specialized in handling economic simulation operations.

Your task is to use the available economy functions to manage persons, their finances, and economic attributes based on the context provided."""

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
    async def add_person_currency(self, id: int, delta: float) -> AddPersonCurrencyResponse:
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
    async def set_person_income(self, id: int, income: float) -> SetPersonIncomeResponse:
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
                agent_id=person.id, step=self._step_counter, t=t,
                currency=person.currency, income=person.income,
                consumption=person.consumption,
            )
        # 持久化环境全局状态
        await self._write_env_state(
            step=self._step_counter, t=t,
            bank_interest_rate=self._bank_interest_rate,
        )
        self._step_counter += 1

    def _dump_state(self) -> dict:
        return {
            "persons": {str(pid): p.model_dump() for pid, p in self._persons.items()},
            "bank_interest_rate": self._bank_interest_rate,
            "last_run_datetime": self._last_run_datetime.isoformat(),
            "gov_tax_brackets": [
                {"cutoff": b.cutoff, "rate": b.rate} for b in self._gov_tax_brackets
            ],
            "step_counter": self._step_counter,
        }

    def _load_state(self, state: dict):
        if "persons" in state:
            self._persons = {
                int(k): EconomyPerson.model_validate(v)
                for k, v in state["persons"].items()
            }
        if "bank_interest_rate" in state:
            self._bank_interest_rate = state["bank_interest_rate"]
        if "last_run_datetime" in state:
            self._last_run_datetime = datetime.fromisoformat(
                state["last_run_datetime"]
            )
        if "gov_tax_brackets" in state:
            self._gov_tax_brackets = [
                TaxBracket(**b) for b in state["gov_tax_brackets"]
            ]
        if "step_counter" in state:
            self._step_counter = state["step_counter"]

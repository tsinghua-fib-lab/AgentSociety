"""
Social Space Environment
This environment provides social communication functionalities for agents.
"""

import asyncio
import json
from collections import defaultdict
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field

from agentsociety2.env import (
    EnvBase,
    tool,
)
from agentsociety2.env.base import dump_int_map, load_int_map
from agentsociety2.storage import ColumnDef
from agentsociety2.storage.workspace_state import atomic_write_text

# 本模块自选的 workspace 布局：<workspace_root>/state/ENV_STATE.json。
_STATE_REL = "state/ENV_STATE.json"


class Message(BaseModel):
    """Message model for social space"""

    sender_id: int
    content: str
    timestamp: datetime
    message_id: int  # Unique identifier for each message
    group_id: int | None = None  # Group ID if this is a group message


class Group(BaseModel):
    """Group model for social space"""

    group_id: int
    name: str
    members: list[int]  # List of agent IDs


# Response models for tool functions
class SendMessageResponse(BaseModel):
    """Response model for send_message() function"""

    sender_id: int = Field(..., description="The ID of the sender agent")
    receiver_id: int = Field(..., description="The ID of the receiver agent")
    content: str = Field(..., description="The content of the message")


class ReceiveMessagesResponse(BaseModel):
    """Response model for receive_messages() function"""

    agent_id: int = Field(..., description="The ID of the agent")
    messages: list[dict] = Field(..., description="List of messages received")


class CreateGroupResponse(BaseModel):
    """Response model for create_group() function"""

    creator_id: int = Field(..., description="The ID of the creator agent")
    group_id: int = Field(..., description="The ID of the created group")
    name: str = Field(..., description="The name of the group")


class JoinGroupResponse(BaseModel):
    """Response model for join_group() function"""

    agent_id: int = Field(..., description="The ID of the agent")
    group_id: int = Field(..., description="The ID of the group")


class LeaveGroupResponse(BaseModel):
    """Response model for leave_group() function"""

    agent_id: int = Field(..., description="The ID of the agent")
    group_id: int = Field(..., description="The ID of the group")


class SendGroupMessageResponse(BaseModel):
    """Response model for send_group_message() function"""

    sender_id: int = Field(..., description="The ID of the sender agent")
    group_id: int = Field(..., description="The ID of the group")
    content: str = Field(..., description="The content of the message")
    recipient_count: int = Field(..., description="The number of recipients")


class SimpleSocialSpace(EnvBase):
    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """Tools mutate shared state under an internal ``asyncio.Lock``."""
        return True

    # 声明式状态持久化
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("total_messages_sent", "INTEGER"),
        ColumnDef("active_groups", "INTEGER"),
        ColumnDef("total_agents", "INTEGER"),
    ]

    def __init__(
        self,
        agent_id_name_pairs: list[tuple[int, str]] | list[list[int | str]],
    ):
        """
        Initialize the Social Space environment.

        :param agent_id_name_pairs: List of (agent_id, name) tuples or list of [agent_id, name] lists. Can be tuples or lists of length 2.
        """
        super().__init__()

        # Convert list format to tuple format if needed
        pairs: list[tuple[int, str]] = []
        for pair in agent_id_name_pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                pairs.append((int(pair[0]), str(pair[1])))
            else:
                raise ValueError(
                    f"Invalid agent_id_name_pair format: {pair}. Expected tuple/list of (int, str)"
                )

        # Individual mailboxes for agents
        self._mailboxes: dict[int, list[Message]] = defaultdict(list)

        # Groups
        self._groups: dict[int, Group] = {}
        self._next_group_id: int = 1
        self._next_message_id: int = 1

        # Names for agents and groups
        self._agent_names: dict[int, str] = {agent_id: name for agent_id, name in pairs}

        # Lock for thread safety
        self._lock = asyncio.Lock()
        self._step_counter: int = 0
        self._total_messages_sent: int = 0

    async def to_workspace(self, workspace_path=None) -> None:
        """写入 ``state/ENV_STATE.json`` （原子写）。pydantic 用 model_dump，``_lock`` 不存盘。"""
        if workspace_path is not None:
            self._bind_workspace(workspace_path)
        if self._workspace_root is None:
            raise RuntimeError("Env module workspace is not bound")
        atomic_write_text(
            self._workspace_root / _STATE_REL,
            json.dumps(
                {
                    "mailboxes": {
                        str(aid): [m.model_dump(mode="json") for m in msgs]
                        for aid, msgs in self._mailboxes.items()
                    },
                    "groups": {
                        str(gid): g.model_dump(mode="json")
                        for gid, g in self._groups.items()
                    },
                    "next_group_id": self._next_group_id,
                    "next_message_id": self._next_message_id,
                    "agent_names": dump_int_map(self._agent_names),
                    "step_counter": self._step_counter,
                    "total_messages_sent": self._total_messages_sent,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    async def restore(self, workspace_path) -> bool:
        """从 ``state/ENV_STATE.json`` 恢复。

        ``_mailboxes`` 恢复为 ``defaultdict(list)`` （工具方法依赖自动建键）；
        ``_lock`` 由 ``__init__`` 重建，不从盘读取。
        """
        self._bind_workspace(workspace_path)
        state_path = self._workspace_root / _STATE_REL
        if not state_path.is_file():
            return False
        state = json.loads(state_path.read_text(encoding="utf-8"))
        mailboxes = load_int_map(state.get("mailboxes"))
        self._mailboxes = defaultdict(
            list,
            {
                aid: [Message.model_validate(m) for m in msgs]
                for aid, msgs in mailboxes.items()
            },
        )
        groups = load_int_map(state.get("groups"))
        self._groups = {gid: Group.model_validate(g) for gid, g in groups.items()}
        self._next_group_id = int(state.get("next_group_id", 1))
        self._next_message_id = int(state.get("next_message_id", 1))
        self._agent_names = {
            aid: str(name)
            for aid, name in load_int_map(state.get("agent_names")).items()
        }
        self._step_counter = int(state.get("step_counter", 0))
        self._total_messages_sent = int(state.get("total_messages_sent", 0))
        return True

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this environment module.
        Includes parameter descriptions and JSON schemas for data models.
        """

        description = f"""{cls.__name__}: Social communication environment module.

**Description:** Provides social communication functionalities including individual mailboxes and group messaging.

**Initialization Parameters (excluding llm):**
- agent_id_name_pairs (List[Tuple[int, str]] | List[List[int | str]]): List of (agent_id, name) pairs. Can be tuples or lists of length 2. Each element should be [agent_id (int), name (str)].

**Example initialization config:**
```json
{{
  "agent_id_name_pairs": [
    [1, "Alice"],
    [2, "Bob"],
    [3, "Charlie"]
  ]
}}
```
"""
        return description

    @classmethod
    def description(cls) -> str:
        """Return a short module description."""
        return "Social communication environment for direct messages and group interactions."

    # Mailbox functions
    @tool(readonly=False)
    async def send_message(
        self,
        sender_id: int,
        receiver_id: int,
        content: str,
    ) -> SendMessageResponse:
        """
        Send a message to an agent's mailbox.

        :param sender_id: The ID of the sender agent
        :param receiver_id: The ID of the receiver agent
        :param content: The content of the message

        :returns: Context containing message details
        """
        async with self._lock:
            # Create message
            timestamp = self.t
            message = Message(
                sender_id=sender_id,
                content=content,
                timestamp=timestamp,
                message_id=self._next_message_id,
            )
            self._next_message_id += 1

            # Add to receiver's mailbox
            self._mailboxes[receiver_id].append(message)
            self._total_messages_sent += 1

            return SendMessageResponse(
                sender_id=sender_id,
                receiver_id=receiver_id,
                content=content,
            )

    @tool(readonly=True, kind="observe")
    async def receive_messages(self, agent_id: int) -> ReceiveMessagesResponse:
        """
        Receive all messages from an agent's mailbox including personal messages and group messages.
        This is like an instant messaging app where all messages are received in one place.

        :param agent_id: The ID of the agent

        :returns: Context containing all messages
        """
        async with self._lock:
            # Collect all messages (personal and group)
            messages = []

            # Get personal messages
            if agent_id in self._mailboxes:
                for message in self._mailboxes[agent_id]:
                    # Get sender name if available
                    sender_name = self._agent_names.get(
                        message.sender_id, f"Agent {message.sender_id}"
                    )
                    message_data = {
                        "type": "personal",
                        "sender_id": message.sender_id,
                        "sender_name": sender_name,
                        "content": message.content,
                        "timestamp": message.timestamp.isoformat(),
                    }
                    # Add group info if it's a group message
                    if message.group_id is not None:
                        message_data["type"] = "group"
                        message_data["group_id"] = message.group_id
                        group_name = (
                            self._groups[message.group_id].name
                            if message.group_id in self._groups
                            else f"Group {message.group_id}"
                        )
                        message_data["group_name"] = group_name
                    messages.append(message_data)
                # Clear personal mailbox
                self._mailboxes[agent_id] = []

            return ReceiveMessagesResponse(
                agent_id=agent_id,
                messages=messages,
            )

    # Group functions
    @tool(readonly=False)
    async def create_group(
        self, creator_id: int, name: str, init_members: list[int]
    ) -> CreateGroupResponse:
        """
        Create a new group.

        :param creator_id: The ID of the agent creating the group
        :param name: The name of the group
        :param init_members: The initial members of the group

        :returns: Context containing group details
        """
        async with self._lock:
            group_id = self._next_group_id
            self._next_group_id += 1

            group = Group(
                group_id=group_id,
                name=name,
                members=[creator_id, *init_members],
            )

            self._groups[group_id] = group

            return CreateGroupResponse(
                creator_id=creator_id,
                group_id=group_id,
                name=name,
            )

    @tool(readonly=False)
    async def join_group(self, agent_id: int, group_id: int) -> JoinGroupResponse:
        """
        Join an agent to a group.

        :param agent_id: The ID of the agent
        :param group_id: The ID of the group

        :returns: Context containing group and agent details
        """
        async with self._lock:
            # Check if group exists
            if group_id not in self._groups:
                return JoinGroupResponse(agent_id=agent_id, group_id=group_id)

            # Check if agent is already in the group
            group = self._groups[group_id]
            if agent_id in group.members:
                return JoinGroupResponse(agent_id=agent_id, group_id=group_id)

            # Add agent to group
            group.members.append(agent_id)

            return JoinGroupResponse(agent_id=agent_id, group_id=group_id)

    @tool(readonly=False)
    async def leave_group(self, agent_id: int, group_id: int) -> LeaveGroupResponse:
        """
        Remove an agent from a group.

        :param agent_id: The ID of the agent
        :param group_id: The ID of the group

        :returns: Context containing group and agent details
        """
        async with self._lock:
            # Check if group exists
            if group_id not in self._groups:
                return LeaveGroupResponse(agent_id=agent_id, group_id=group_id)

            # Check if agent is in the group
            group = self._groups[group_id]
            if agent_id not in group.members:
                return LeaveGroupResponse(agent_id=agent_id, group_id=group_id)

            # Remove agent from group
            group.members.remove(agent_id)

            # If group is empty, remove it
            if len(group.members) == 0:
                del self._groups[group_id]

            return LeaveGroupResponse(agent_id=agent_id, group_id=group_id)

    @tool(readonly=False)
    async def send_group_message(
        self, sender_id: int, group_id: int, content: str
    ) -> SendGroupMessageResponse:
        """
        Send a message to all members of a group. The message is forwarded to each member's mailbox.

        :param sender_id: The ID of the sender agent
        :param group_id: The ID of the group
        :param content: The content of the message

        :returns: Context containing message details
        """
        async with self._lock:
            # Check if group exists
            if group_id not in self._groups:
                return SendGroupMessageResponse(
                    sender_id=sender_id,
                    group_id=group_id,
                    content=content,
                    recipient_count=0,
                )

            # Check if sender is in the group
            group = self._groups[group_id]
            if sender_id not in group.members:
                return SendGroupMessageResponse(
                    sender_id=sender_id,
                    group_id=group_id,
                    content=content,
                    recipient_count=0,
                )

            # Create message
            timestamp = self.t
            message = Message(
                sender_id=sender_id,
                content=content,
                timestamp=timestamp,
                message_id=self._next_message_id,
                group_id=group_id,
            )
            self._next_message_id += 1

            # Forward message to each member's mailbox (including sender)
            recipient_count = 0
            for member_id in group.members:
                self._mailboxes[member_id].append(message)
                recipient_count += 1
            self._total_messages_sent += 1

            return SendGroupMessageResponse(
                sender_id=sender_id,
                group_id=group_id,
                content=content,
                recipient_count=recipient_count,
            )

    async def step(self, tick: int, t: datetime):
        """
        Run forward one step.

        :param tick: The number of ticks of this simulation step.
        :param t: The current datetime of the simulation after this step with the ticks.
        """
        async with self._lock:
            self.t = t

            # Clean up empty groups
            groups_to_remove = []
            for group_id, group in self._groups.items():
                # If group is empty (no members), mark for removal
                if len(group.members) == 0:
                    groups_to_remove.append(group_id)

            # Remove empty groups
            for group_id in groups_to_remove:
                del self._groups[group_id]

        # 持久化环境全局状态
        await self._write_env_state(
            step=self._step_counter,
            t=t,
            total_messages_sent=self._total_messages_sent,
            active_groups=len(self._groups),
            total_agents=len(self._agent_names),
        )
        self._step_counter += 1

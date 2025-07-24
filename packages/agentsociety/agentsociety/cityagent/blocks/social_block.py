# Due to the current limitations of the simulator's support, only NoneBlock, MessageBlock, and FindPersonBlock are available in the Dispatcher.

from typing import Any, Optional

import json

import json_repair

from ...agent import (
    AgentToolbox,
    Block,
    FormatPrompt,
    BlockParams,
    DotDict,
    BlockContext,
)
from ...logger import get_logger
from ...memory import Memory
from ...agent.dispatcher import BlockDispatcher
from .utils import TIME_ESTIMATE_PROMPT, clean_json_response
from ..sharing_params import SocietyAgentBlockOutput
from pydantic import Field


class MessagePromptManager:
    """
    Manages the creation of message prompts by dynamically formatting templates with agent-specific data.
    """

    def __init__(self):
        pass

    async def get_prompt(
        self, memory, step: dict[str, Any], target: str, template: str
    ):
        """Generates a formatted prompt for message creation.

        Args:
            memory: Agent's memory to retrieve status data.
            step: Current workflow step containing intention and context.
            target: ID of the target agent for communication.
            template: Raw template string to be formatted.

        Returns:
            Formatted prompt string with placeholders replaced by agent-specific data.
        """
        # Retrieve data
        relationships = await memory.status.get("relationships") or {}
        chat_histories = await memory.status.get("chat_histories") or {}

        # Build discussion topic constraints
        discussion_constraint = ""
        topics = await memory.status.get("attitude")
        topics = topics.keys()
        if topics:
            topics = ", ".join(f'"{topic}"' for topic in topics)
            discussion_constraint = (
                f"Limit your discussion to the following topics: {topics}."
            )

        # Format prompt
        format_prompt = FormatPrompt(template)
        await format_prompt.format(
            gender=await memory.status.get("gender") or "",
            education=await memory.status.get("education") or "",
            personality=await memory.status.get("personality") or "",
            occupation=await memory.status.get("occupation") or "",
            relationship_score=relationships.get(target, 50),
            intention=step.get("intention", ""),
            emotion_types=await memory.status.get("emotion_types"),
            thought=await memory.status.get("thought"),
            chat_history=(
                chat_histories.get(target, "")
                if isinstance(chat_histories, dict)
                else ""
            ),
            discussion_constraint=discussion_constraint,
        )

        return format_prompt.to_dialog()


class SocialNoneBlock(Block):
    """
    NoneBlock
    """

    name = "SocialNoneBlock"
    description = "Handle all other cases"

    def __init__(self, toolbox: AgentToolbox, agent_memory: Memory):
        super().__init__(toolbox=toolbox, agent_memory=agent_memory)
        self.guidance_prompt = FormatPrompt(template=TIME_ESTIMATE_PROMPT)

    async def forward(self, step, context):
        """Executes default behavior when no specific block matches the intention.

        Args:
            step: Current workflow step with 'intention' and other metadata.
            context: Additional execution context (e.g., agent's plan).

        Returns:
            A result dictionary indicating success/failure, time consumed, and execution details.
        """
        await self.guidance_prompt.format(
            plan=context["plan"],
            intention=step["intention"],
            emotion_types=await self.memory.status.get("emotion_types"),
        )
        result = await self.llm.atext_request(
            self.guidance_prompt.to_dialog(), response_format={"type": "json_object"}
        )
        result = clean_json_response(result)
        try:
            result: Any = json_repair.loads(result)
            node_id = await self.memory.stream.add(
                topic="social", description=f"I {step['intention']}"
            )
            return {
                "success": True,
                "evaluation": f'Finished {step["intention"]}',
                "consumed_time": result["time"],
                "node_id": node_id,
            }
        except Exception as e:
            get_logger().warning(
                f"Error occurred while parsing the evaluation response: {e}, original result: {result}"
            )
            node_id = await self.memory.stream.add(
                topic="social", description=f"I failed to execute {step['intention']}"
            )
            return {
                "success": False,
                "evaluation": f'Failed to execute {step["intention"]}',
                "consumed_time": 5,
                "node_id": node_id,
            }


class FindPersonBlock(Block):
    """
    Block for selecting an appropriate agent to socialize with based on relationship strength and context.
    """

    name = "FindPersonBlock"
    description = "Find a suitable person to socialize with"

    def __init__(self, toolbox: AgentToolbox, agent_memory: Memory):
        super().__init__(
            toolbox=toolbox,
            agent_memory=agent_memory,
        )

        self.prompt = """
        Based on the following information, help me select the most suitable friend to interact with:

        1. Your Profile:
           - Gender: {gender}
           - Education: {education}
           - Personality: {personality}
           - Occupation: {occupation}

        2. Your Current Intention: {intention}

        3. Your Current Emotion: {emotion_types}

        4. Your Current Thought: {thought}

        5. Your Friends List (shown as index-to-relationship pairs):
           {friend_info}
           Note: For each friend, the relationship strength (0-100) indicates how close we are

        Please analyze and select:
        1. The most appropriate friend based on relationship strength and my current intention
        2. Whether we should meet online or offline

        Requirements:
        - You must respond in this exact format: [mode, friend_index]
        - mode must be either 'online' or 'offline'
        - friend_index must be an integer representing the friend's position in the list (starting from 0)
        
        Example valid outputs:
        ['online', 0]  - means meet the first friend online
        ['offline', 2] - means meet the third friend offline
        """

    async def forward(self, context: DotDict):
        """Identifies a target agent and interaction mode (online/offline).

        Args:
            context: Additional execution context (may store selected target).

        Returns:
            Result dict with target agent, interaction mode, and execution status.
        """
        try:
            # Get friends list and relationship strength
            private_friends = await self.memory.status.get("friends", [])
            public_friends = await self.memory.status.get("public_friends", [])
            friends = private_friends + public_friends
            relationships = await self.memory.status.get("relationships", {})

            if not friends:
                node_id = await self.memory.stream.add(
                    topic="social",
                    description="I can't find any friends to contact with.",
                )
                return {
                    "success": False,
                    "evaluation": "No friends found in social network",
                    "consumed_time": 5,
                    "node_id": node_id,
                }

            # Create a list of friends with all information
            friend_info = []
            index_to_id = {}

            for i, friend_id in enumerate(friends):
                relationship_strength = relationships.get(friend_id, 0)
                friend_info.append(
                    {"index": i, "relationship_strength": relationship_strength}
                )
                index_to_id[i] = friend_id

            # Format friend information for easier reading
            formatted_friend_info = {
                i: {"relationship_strength": info["relationship_strength"]}
                for i, info in enumerate(friend_info)
            }

            # Format the prompt
            formatted_prompt = FormatPrompt(self.prompt)
            await formatted_prompt.format(
                gender=str(await self.memory.status.get("gender")),
                education=str(await self.memory.status.get("education")),
                personality=str(await self.memory.status.get("personality")),
                occupation=str(await self.memory.status.get("occupation")),
                intention=str(context["current_step"].get("intention", "socialize")),
                emotion_types=str(await self.memory.status.get("emotion_types")),
                thought=str(await self.memory.status.get("thought")),
                friend_info=str(formatted_friend_info),
            )

            # Get LLM response
            response = await self.llm.atext_request(
                formatted_prompt.to_dialog(), timeout=300
            )

            try:
                # Parse the response
                mode, friend_index = eval(response)

                # Validate the response format
                if not isinstance(mode, str) or mode not in ["online", "offline"]:
                    raise ValueError("Invalid mode")
                if not isinstance(friend_index, int) or friend_index not in index_to_id:
                    raise ValueError("Invalid friend index")

                # Convert index to ID
                target = index_to_id[friend_index]
                if context is not None:
                    context["target"] = target
            except Exception:
                # If parsing fails, select the friend with the strongest relationship as the default option
                target = (
                    max(relationships.items(), key=lambda x: x[1])[0]
                    if relationships
                    else friends[0]
                )
                mode = "online"

            node_id = await self.memory.stream.add(
                topic="social",
                description=f"I selected the friend {target} for {mode} interaction",
            )
            return {
                "success": True,
                "evaluation": f"Selected friend {target} for {mode} interaction",
                "consumed_time": 15,
                "mode": mode,
                "target": target,
                "node_id": node_id,
            }

        except Exception as e:
            node_id = await self.memory.stream.add(
                topic="social",
                description="I can't find any friends to socialize with.",
            )
            return {
                "success": False,
                "evaluation": f"Error in finding person: {str(e)}",
                "consumed_time": 5,
                "node_id": node_id,
            }


class MessageBlock(Block):
    """Generate and send messages"""

    name = "MessageBlock"
    description = "Send a message to someone"
    NeedAgent = True

    def __init__(self, toolbox: AgentToolbox, agent_memory: Memory):
        super().__init__(
            toolbox=toolbox,
            agent_memory=agent_memory,
        )
        self.find_person_block = FindPersonBlock(toolbox, agent_memory)

        # configurable fields
        self.default_message_template = """
        As a {gender} {occupation} with {education} education and {personality} personality,
        generate a message for a friend (relationship strength: {relationship_score}/100)
        about {intention}.

        Your current emotion: {emotion_types}
        Your current thought: {thought}
        
        Previous chat history:
        {chat_history}
        
        Generate a natural and contextually appropriate message.
        Keep it under 100 characters.
        The message should reflect my personality and background.
        {discussion_constraint}
        """

        self.prompt_manager = MessagePromptManager()

    def _serialize_message(self, message: str, propagation_count: int) -> str:
        """Serializes a message into a JSON string for transmission.

        Args:
            message: Plain text message content.
            propagation_count: Number of times the message can be forwarded.

        Returns:
            JSON string with message and metadata.
        """
        try:
            return json.dumps(
                {"content": message, "propagation_count": propagation_count},
                ensure_ascii=False,
            )
        except Exception as e:
            get_logger().warning(f"Error serializing message: {e}")
            return message

    async def forward(self, context: DotDict):
        """Generates a message, sends it to the target, and updates chat history.

        Args:
            context: Execution context (may contain pre-selected target).

        Returns:
            Result dict with message content, target, and execution status.
        """
        target = None
        try:
            # Get target from context or find one
            target = context.get("target") if context else None
            if not target:
                result = await self.find_person_block.forward(context)
                if not result["success"]:
                    return {
                        "success": False,
                        "evaluation": "Could not find target for message",
                        "consumed_time": 5,
                        "node_id": result["node_id"],
                    }
                target = result["target"]

            # Get formatted prompt using prompt manager
            formatted_prompt = await self.prompt_manager.get_prompt(
                self.memory,
                context["current_step"],
                target,
                self.default_message_template,
            )

            # Generate message
            message = await self.llm.atext_request(formatted_prompt, timeout=300)
            if not message:
                message = "Hello! How are you?"

            # Update chat history with proper format
            chat_histories = await self.memory.status.get("chat_histories") or {}
            if not isinstance(chat_histories, dict):
                chat_histories = {}
            if target not in chat_histories:
                chat_histories[target] = ""
            elif len(chat_histories[target]) > 0:
                chat_histories[target] += ", "
            chat_histories[target] += f"me: {message}"

            await self.memory.status.update("chat_histories", chat_histories)

            # Send message
            serialized_message = self._serialize_message(message, 1)
            await self.agent.send_message_to_agent(target, serialized_message)

            node_id = await self.memory.stream.add(
                topic="social", description=f"I sent a message to {target}: {message}"
            )
            return {
                "success": True,
                "evaluation": f"Sent message to {target}: {message}",
                "consumed_time": 10,
                "node_id": node_id,
            }

        except Exception as e:
            node_id = await self.memory.stream.add(
                topic="social", description=f"I can't send a message to {target}"
            )
            return {
                "success": False,
                "evaluation": f"Error in sending message: {str(e)}",
                "consumed_time": 5,
                "node_id": node_id,
            }


class SocialBlockParams(BlockParams): ...


class SocialBlockContext(BlockContext):
    target: Optional[int] = Field(
        default=None,
        description="The target agent id that the agent is going to socialize with",
    )


class SocialBlock(Block):
    """
    Orchestrates social interactions by dispatching to appropriate sub-blocks.
    """

    ParamsType = SocialBlockParams
    OutputType = SocietyAgentBlockOutput
    ContextType = SocialBlockContext
    NeedAgent = True
    name = "SocialBlock"
    description = "Do social interactions, for example, find a friend, send a message, and other social activities."
    actions = {
        "find_person": "Support the find person action, determine the social target.",
        "message": "Support the message action, send a message to the social target.",
        "social_none": "Support other social operations",
    }

    def __init__(
        self,
        toolbox: AgentToolbox,
        agent_memory: Memory,
        block_params: Optional[SocialBlockParams] = None,
    ):
        super().__init__(
            toolbox=toolbox,
            agent_memory=agent_memory,
            block_params=block_params,
        )
        self.find_person_block = FindPersonBlock(toolbox, agent_memory)
        self.message_block = MessageBlock(toolbox, agent_memory)
        self.noneblock = SocialNoneBlock(toolbox, agent_memory)
        self.dispatcher = BlockDispatcher(toolbox, agent_memory)

        self.trigger_time = 0
        self.token_consumption = 0

        self.dispatcher.register_blocks(
            [self.find_person_block, self.message_block, self.noneblock]
        )

    async def forward(self, agent_context: DotDict) -> SocietyAgentBlockOutput:
        """Main entry point for social interactions. Dispatches to sub-blocks based on context.

        Args:
            step: Workflow step containing intention and metadata.
            context: Additional execution context.

        Returns:
            Result dict from the executed sub-block.
        """
        try:
            self.trigger_time += 1
            
            # make sure the message_block has the agent reference
            if hasattr(self.message_block, 'NeedAgent') and self.message_block.NeedAgent:
                self.message_block.set_agent(self.agent)

            context = agent_context | self.context

            # Select the appropriate sub-block using dispatcher
            selected_block = await self.dispatcher.dispatch(context)
            if not selected_block:
                return self.OutputType(
                    success=False,
                    evaluation=f"Failed to complete social interaction with default behavior: {context['current_intention']}",
                    consumed_time=15,
                    node_id=None,
                )

            # Execute the selected sub-block and get the result
            result = await selected_block.forward(context)

            return self.OutputType(**result)

        except Exception as e:
            return self.OutputType(
                success=False,
                evaluation=f"Failed to complete social interaction with default behavior: {str(e)}",
                consumed_time=15,
                node_id=None,
            )

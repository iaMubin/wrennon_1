"""
Executes whatever tools the manager planned this pass.

CHANGE (LLM-quality rewrite): gathered_context and tool_call_history
now ACCUMULATE across manager<->tool_executor loop iterations instead
of being overwritten. planned_tools itself is left untouched after
running (the manager overwrites it fresh on every pass anyway) so that
callers reading the final state — e.g. the semantic-cache check in
websocket_routes.py — still see what the *last* decision was. Use
tool_call_history if you need everything that ran across the whole
turn, not just the last pass.
"""

from app.graph.state import ConversationState
from app.services.tools import TOOL_EXECUTORS
from app.logger import logger
import json
import time


async def tool_executor_node(state: ConversationState) -> ConversationState:
    start_time = time.time()
    logger.info("Tool Executor Node: executing planned tools...")
    planned_tools = state.get("planned_tools", [])

    gathered_context = list(state.get("gathered_context", []))
    tool_call_history = list(state.get("tool_call_history", []))

    for tool_call in planned_tools:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True)}"

        if tool_name in TOOL_EXECUTORS:
            logger.info(f"Executing tool: {tool_name} with args {tool_args}")
            try:
                result = await TOOL_EXECUTORS[tool_name](tool_args)
                gathered_context.append(f"Result from {tool_name}:\n{result}")
            except Exception as e:
                logger.error(f"Error executing {tool_name}: {e}")
                gathered_context.append(f"Failed to execute {tool_name}: {e}")
            tool_call_history.append(signature)
        else:
            logger.warning(f"Unknown tool requested: {tool_name}")

    state["gathered_context"] = gathered_context
    state["tool_call_history"] = tool_call_history

    # Counts as a real node mutation (unlike a conditional-edge router),
    # so this is the correct place for the loop counter to live — see
    # builder.py's route_after_tools, which only ever reads this value.
    state["iteration_count"] = state.get("iteration_count", 0) + 1

    logger.info(f"[TIMING] Tool Executor Node took {time.time() - start_time:.3f}s")
    return state

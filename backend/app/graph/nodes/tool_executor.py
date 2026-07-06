from app.graph.state import ConversationState
from app.services.tools import TOOL_EXECUTORS
from app.logger import logger

async def tool_executor_node(state: ConversationState) -> ConversationState:
    logger.info("Worker Node: Executing planned tools...")
    planned_tools = state.get("planned_tools", [])
    gathered_context = []
    
    for tool_call in planned_tools:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        
        if tool_name in TOOL_EXECUTORS:
            logger.info(f"Executing tool: {tool_name} with args {tool_args}")
            try:
                result = await TOOL_EXECUTORS[tool_name](tool_args)
                gathered_context.append(f"Result from {tool_name}:\n{result}")
            except Exception as e:
                logger.error(f"Error executing {tool_name}: {e}")
                gathered_context.append(f"Failed to execute {tool_name}: {e}")
        else:
            logger.warning(f"Unknown tool requested: {tool_name}")
            
    state["gathered_context"] = gathered_context
    return state

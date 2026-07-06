import json
from app.graph.state import ConversationState
from app.services.llm import _safe_llm_call, mask_pii
from app.logger import logger

async def manager_node(state: ConversationState) -> ConversationState:
    logger.info("Manager Node: Planning execution...")
    
    system_prompt = (
        "You are an expert Manager LLM orchestrating a customer support chatbot. "
        "Your job is to analyze the conversation history and the latest user message to determine what tools need to be executed.\n\n"
        "Available Tools:\n"
        "1. get_order_status: Fetches tracking information. Requires 'order_id'.\n"
        "2. If the user provides an order ID you can use get_order_status immediately.\n"
        "3. search_knowledge_base: Fetches policy info (returns, shipping, etc.). Requires 'query'.\n\n"
        "Rules:\n"
        "1. If the user is just saying hello, saying thank you, or having small talk, you do not need any tools.\n"
        "2. If the user asks for something outside our capabilities (e.g., 'cancel my order', 'refund me', 'change my address') OR is highly frustrated, set 'handoff_required' to true.\n"
        "3. You MUST output your decision as a JSON object with this exact structure:\n"
        "{\n"
        "  \"tools_to_run\": [{\"name\": \"tool_name\", \"args\": {\"arg_name\": \"value\"}}],\n"
        "  \"handoff_required\": boolean\n"
        "}\n\n"
        "EXAMPLES:\n"
        "Example 1: User says 'Where is order 1002?'\n"
        "Output: {\"tools_to_run\": [{\"name\": \"get_order_status\", \"args\": {\"order_id\": \"1002\"}}], \"handoff_required\": false}\n\n"
        "Example 3: User says 'What is your return policy?'\n"
        "Output: {\"tools_to_run\": [{\"name\": \"search_knowledge_base\", \"args\": {\"query\": \"return policy\"}}], \"handoff_required\": false}\n\n"
        "Example 4: User says 'Cancel my account'\n"
        "Output: {\"tools_to_run\": [], \"handoff_required\": true}\n"
    )

    llm_messages = [{"role": "system", "content": system_prompt}]
    
    # Add recent conversation history (last 6 messages)
    recent_messages = state["messages"][-6:] if len(state["messages"]) > 6 else state["messages"]
    for msg in recent_messages:
        role = "user" if msg.type == "human" else "assistant"
        content = mask_pii(msg.content) if role == "user" else msg.content
        llm_messages.append({"role": role, "content": content})

    try:
        result_str = await _safe_llm_call(llm_messages, temperature=0.0, max_tokens=300, is_json=True)
        decision = json.loads(result_str)
        
        state["planned_tools"] = decision.get("tools_to_run", [])
        if decision.get("handoff_required"):
            logger.warning("Manager LLM requested handoff.")
            state["handoff_requested"] = True
            
    except Exception as e:
        logger.error(f"Failed to parse Manager LLM JSON: {e}")
        state["planned_tools"] = []
        
    return state

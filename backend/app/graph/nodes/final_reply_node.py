from langchain_core.messages import AIMessage
from app.graph.state import ConversationState
from app.services.llm import _safe_llm_call, mask_pii
from app.logger import logger

def final_reply_node(state: ConversationState) -> ConversationState:
    logger.info("Final Reply Node: Generating contextual response...")
    
    system_instruction = (
        "You are an empathetic, highly experienced human customer support agent named Alex working for an online store. "
        "Formulate a reply based on the provided conversation history and 'Gathered Context'.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. BE HUMAN: Adapt your tone to the customer's sentiment. If they are frustrated, be deeply empathetic and apologetic. If they are happy, be warm. Do NOT use repetitive robotic phrases like 'I'd be happy to' or 'I'm sorry for the inconvenience'. Speak naturally.\n"
        "2. NO HALLUCINATIONS: If the customer asks for tracking/status, you MUST ONLY provide it if it is in the 'Gathered Context'. If the context is empty or missing, DO NOT pretend you are 'fetching it', 'pulling it now', or 'will share it shortly'. You cannot fetch anything yourself. You must either ask for missing details or say you cannot find it.\n"
        "3. You must keep the conversation moving. Answer the question completely using the Gathered Context, or ask for the missing Order ID.\n"
        "4. If 'Gathered Context' says 'Missing order_id', casually ask the user for the missing detail.\n"
        "5. Keep responses concise and natural. Don't over-explain."
    )
    
    context_parts = []
    
    if state.get("gathered_context"):
        context_parts.append("Gathered Context from internal systems:")
        context_parts.extend(state["gathered_context"])
        
    if state.get("handoff_requested"):
        context_parts.append(
            "IMPORTANT: The system has escalated this chat to a real human manager behind the scenes. "
            "Reply to the customer naturally (e.g. apologize that you cannot fully resolve it, "
            "and mention you are bringing in a senior specialist to take over right away). "
            "Make it sound like you are personally handing them over to a colleague. DO NOT say 'ticket created'."
        )
        
    if state.get("conversation_summary"):
        context_parts.append(f"Previous Conversation Summary:\n{state['conversation_summary']}")

    context_text = "\n\n".join(context_parts) if context_parts else "No additional context available."
    
    llm_messages = [{"role": "system", "content": system_instruction}]
    
    # Add conversation history
    recent_messages = state["messages"][-10:]
    for msg in recent_messages[:-1]:  
        role = "user" if msg.type == "human" else "assistant"
        content = mask_pii(msg.content) if role == "user" else msg.content
        llm_messages.append({"role": role, "content": content})
        
    # Append the last message along with the context block
    last_user_msg = mask_pii(recent_messages[-1].content)
    final_prompt = f"System Context/Data:\n{context_text}\n\nUser Message: {last_user_msg}"
    llm_messages.append({"role": "user", "content": final_prompt})
    
    reply = _safe_llm_call(llm_messages, temperature=0.3, max_tokens=400)
    if not reply:
        reply = "I'm sorry, I couldn't process that right now. Could you please try again?"
        
    state["messages"].append(AIMessage(content=reply))
    return state

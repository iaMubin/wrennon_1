from langchain_core.messages import AIMessage
from app.graph.state import ConversationState
from app.services.llm import _safe_llm_call, mask_pii
from app.logger import logger

def final_reply_node(state: ConversationState) -> ConversationState:
    logger.info("Final Reply Node: Generating contextual response...")
    
    system_instruction = (
        "You are an expert customer support agent for an online store. "
        "Formulate a reply to the customer based on the provided conversation history and 'Gathered Context'.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. Keep your response concise, professional, and natural. Don't be robotic.\n"
        "2. If the user is just greeting, politely greet back and ask how you can help.\n"
        "3. If 'Gathered Context' contains information (like order tracking or policy details), use it to answer the customer directly.\n"
        "4. If 'Gathered Context' says 'Missing order_id or email', politely ask the user to provide the missing detail.\n"
        "5. Do NOT repeat yourself unnecessarily.\n"
        "6. Do NOT invent policies or tracking details not present in the Gathered Context."
    )
    
    context_parts = []
    
    if state.get("gathered_context"):
        context_parts.append("Gathered Context from internal systems:")
        context_parts.extend(state["gathered_context"])
        
    if state.get("handoff_requested"):
        context_parts.append(
            "IMPORTANT: The Manager AI has determined this issue requires a human agent and has notified them behind the scenes. "
            "Reply to the customer naturally (e.g. apologize that you cannot fully resolve it, "
            "and mention you will have someone look into it). DO NOT say 'ticket created' or explicitly announce a transfer."
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

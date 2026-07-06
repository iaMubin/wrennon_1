from langchain_core.messages import AIMessage
from app.graph.state import ConversationState
from app.services.llm import _safe_llm_call, mask_pii
from app.logger import logger
import time

async def final_reply_node(state: ConversationState) -> ConversationState:
    start_time = time.time()
    logger.info("Final Reply Node: Generating contextual response...")
    
    system_instruction = (
        "You are an Expert Support Assistant for Wrennon, a premium e-commerce brand. "
        "Your role is to craft the final response to the customer based on their query and any tools used.\n\n"
        "Guidelines:\n"
        "- Be polite, professional, and empathetic. Address the customer's core need directly.\n"
        "- You MUST disclose that you are an AI assistant in your greeting and responses when appropriate, as required by transparency laws. DO NOT pretend to be a human agent.\n"
        "- If context is provided, integrate it naturally into your reply. Do not say 'based on the context provided' or 'I found this'.\n"
        "- If no context is provided and the user asks a specific policy question, you can say you don't know and offer to connect them to a human agent.\n"
        "- If the conversation is marked as 'resolved' (the user has indicated they have no more questions or are saying goodbye), provide a warm closing message and do not ask any further questions."
    )
    
    if state.get("conversation_mode") == "resolved":
        system_instruction += "\n\nNOTE: This conversation has been marked as resolved. Provide a polite closing message (e.g. 'You're welcome! Let us know if you need anything else. Have a great day!'). Do not ask if they need further assistance."
        
    if state.get("gathered_context"):
        system_instruction += f"\n\nContext gathered from tools:\n{state['gathered_context']}"
    
    context_parts = []
        
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
    
    reply = await _safe_llm_call(llm_messages, temperature=0.3, max_tokens=400)
    if not reply:
        reply = "I'm sorry, I couldn't process that right now. Could you please try again?"
        
    state["messages"].append(AIMessage(content=reply))
    logger.info(f"[TIMING] Final Reply Node took {time.time() - start_time:.3f}s")
    return state

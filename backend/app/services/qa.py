import json
from app.db.session import SessionLocal
from app.db.models import Conversation, AnalyticsScorecard, KnowledgeGap
from app.services.llm import _safe_llm_call
from app.logger import logger

async def process_resolved_conversation_tasks(conversation_id: str):
    """Entry point for FastAPI BackgroundTasks when a conversation is resolved."""
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv:
            return

        messages = conv.messages
        if not messages:
            return

        transcript = "\n".join([f"{m.sender}: {m.content}" for m in messages])

        # 1. Generate Scorecard
        await _generate_scorecard(conversation_id, transcript, db)

        # 2. Detect Knowledge Gap (only relevant if handed off to a human agent)
        if conv.handled_by:
            await _detect_knowledge_gap(conversation_id, transcript, db)

    except Exception as e:
        logger.error(f"Failed to process background tasks for conv {conversation_id}: {e}")
    finally:
        db.close()


async def _generate_scorecard(conversation_id: str, transcript: str, db):
    existing = db.query(AnalyticsScorecard).filter_by(conversation_id=conversation_id).first()
    if existing:
        return

    prompt = [
        {"role": "system", "content": (
            "You are an expert Quality Assurance bot for customer support. "
            "Analyze the transcript and provide a JSON scorecard.\n"
            "Format exactly as:\n"
            "{\n"
            "  \"empathy_score\": 1-10,\n"
            "  \"accuracy_score\": 1-10,\n"
            "  \"resolution_score\": 1-10,\n"
            "  \"csat_prediction\": 1-5,\n"
            "  \"feedback_notes\": \"Very short (max 10 words) on-point feedback\"\n"
            "}"
        )},
        {"role": "user", "content": f"Transcript:\n{transcript}"}
    ]

    try:
        res = await _safe_llm_call(prompt, is_json=True, max_tokens=300)
        data = json.loads(res)
        scorecard = AnalyticsScorecard(
            conversation_id=conversation_id,
            empathy_score=data.get("empathy_score"),
            accuracy_score=data.get("accuracy_score"),
            resolution_score=data.get("resolution_score"),
            csat_prediction=data.get("csat_prediction"),
            feedback_notes=data.get("feedback_notes")
        )
        db.add(scorecard)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to generate scorecard: {e}")


async def _detect_knowledge_gap(conversation_id: str, transcript: str, db):
    prompt = [
        {"role": "system", "content": (
            "You analyze human agent transcripts to find Knowledge Base gaps. "
            "Did the customer ask a specific policy/process question that the human agent answered, which should be documented? "
            "If NO, return: {\"has_gap\": false}\n"
            "If YES, return: {\n"
            "  \"has_gap\": true,\n"
            "  \"question\": \"The specific question asked\",\n"
            "  \"draft_article\": \"A drafted markdown article containing the human's answer to add to the KB\"\n"
            "}"
        )},
        {"role": "user", "content": f"Transcript:\n{transcript}"}
    ]

    try:
        res = await _safe_llm_call(prompt, is_json=True, max_tokens=500)
        data = json.loads(res)
        if data.get("has_gap") and data.get("draft_article"):
            gap = KnowledgeGap(
                conversation_id=conversation_id,
                question=data.get("question", "Unknown Question"),
                draft_article=data.get("draft_article")
            )
            db.add(gap)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to detect KB gap: {e}")

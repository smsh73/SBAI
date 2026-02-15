"""AI 챗봇 라우터"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from app.services.chatbot_service import chat

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str = ""
    message: str


class ChatResponse(BaseModel):
    response: str
    sql_query: str | None = None
    data: list | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """AI 챗봇 대화 API"""
    result = await chat(req.session_id, req.message)
    return ChatResponse(**result)

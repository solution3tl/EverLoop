"""
对话接口 - SSE 流式推送端点
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.streaming_handler import stream_chat_response, StreamContext
from init.general_agent import get_or_init_agent
from langchain_core.messages import HumanMessage

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None
    model_name: Optional[str] = None
    agent_config: Optional[dict] = {}


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE 流式对话端点"""
    user_id = getattr(request.state, "user_id", "anonymous")
    thread_id = req.thread_id or str(uuid.uuid4())[:8]

    # 确保 AgentLoop 已初始化
    agent_loop = await get_or_init_agent(req.model_name)

    user_message = HumanMessage(content=req.message)
    stream_ctx = StreamContext()

    async def generate():
        async for chunk in stream_chat_response(
            agent_loop=agent_loop,
            user_message=user_message,
            thread_id=thread_id,
            user_id=user_id,
            stream_ctx=stream_ctx,
        ):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Thread-Id": thread_id,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "X-Thread-Id",
        },
    )


@router.get("/history")
async def get_history(thread_id: str, limit: int = 50, request: Request = None):
    """获取历史对话"""
    from database import crud
    session = await crud.get_session_by_thread_id(thread_id)
    if not session:
        return {"messages": [], "thread_id": thread_id}

    messages = await crud.get_messages_by_session(session.id, limit=limit)
    return {
        "thread_id": thread_id,
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ],
    }


@router.get("/models")
async def list_models():
    """获取可用模型列表"""
    from init.general_agent import get_available_models
    from llm.model_config import get_default_config
    default = get_default_config()
    return {
        "models": get_available_models(),
        "default": default.provider if default else None,
    }


@router.post("/reload-model")
async def reload_model(model_name: str, request: Request):
    """切换模型（仅管理员）"""
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可切换模型")

    from init.general_agent import reload_agent
    await reload_agent(model_name)
    return {"message": f"已切换到模型 {model_name}"}

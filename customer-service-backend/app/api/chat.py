"""对外接口：与《客服后端接口文档》完全一致。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.deps import get_dialogue_service
from app.api.schemas import ChatRequest, ChatResponse, HistoryResponse
from app.services.dialogue_service import DialogueService

router = APIRouter(prefix="/api", tags=["对话"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="发送一条消息",
    description="text 与 object 二选一；object 表示用户点击了订单/商品卡片。",
)
async def chat(
    request: ChatRequest,
    service: DialogueService = Depends(get_dialogue_service),
) -> ChatResponse:
    return await service.chat(request)


@router.get(
    "/chat/history",
    response_model=HistoryResponse,
    summary="获取某个用户的全部历史对话",
)
async def history(
    sender_id: str = Query(..., description="用户标识"),
    service: DialogueService = Depends(get_dialogue_service),
) -> HistoryResponse:
    return await service.history(sender_id)


class TtsRequest(BaseModel):
    text: str


@router.post(
    "/chat/tts",
    summary="语音播报（未接入）",
    description="前端语音按钮调用的接口。当前版本未接入 TTS 服务，返回 501，前端会自动降级为纯文字。",
)
async def tts(request: TtsRequest) -> None:
    raise HTTPException(
        status_code=501,
        detail="语音播报未接入。如需启用，可在此处对接 DashScope CosyVoice 或 Azure TTS。",
    )

"""多模态 content block 构造辅助函数。

产出与 LangChain / OpenAI 风格兼容的字典结构，便于把文本、图片与音频
拼成一条多模态消息；不涉及任何网络调用。
"""
from __future__ import annotations

import base64
from typing import Any


def text_block(text: str) -> dict[str, Any]:
    """构造文本内容块。"""
    return {"type": "text", "text": text}


def image_url_block(url: str, detail: str = "auto") -> dict[str, Any]:
    """构造图片 URL 内容块。"""
    return {"type": "image_url", "image_url": {"url": url, "detail": detail}}


def image_base64_block(data: bytes, media_type: str = "image/png") -> dict[str, Any]:
    """把图片字节编码成 data URI 内容块。"""
    encoded = base64.b64encode(data).decode("ascii")
    return image_url_block(f"data:{media_type};base64,{encoded}")


def audio_block(data: bytes, media_type: str = "audio/wav") -> dict[str, Any]:
    """构造音频内容块；media_type 形如 ``audio/wav``，后缀作为 format。"""
    fmt = media_type.split("/", 1)[-1]
    return {
        "type": "input_audio",
        "input_audio": {
            "data": base64.b64encode(data).decode("ascii"),
            "format": fmt,
        },
    }


def build_content(
    text: str | None = None,
    images: list[str] | None = None,
    audios: list[bytes] | None = None,
) -> list[dict[str, Any]]:
    """按「文本 -> 图片 -> 音频」顺序拼装完整 content 列表。"""
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append(text_block(text))
    blocks.extend(image_url_block(url) for url in images or [])
    blocks.extend(audio_block(data) for data in audios or [])
    return blocks

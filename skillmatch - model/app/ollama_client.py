"""Ollama 로컬 LLM 호출 클라이언트.

사전 준비:
  ollama serve
  ollama pull gemma3n:e2b   # 또는 OLLAMA_MODEL 환경변수로 원하는 모델 지정
"""
from __future__ import annotations

import json
import os

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3n:e2b")
# 2번째 LLM 호출은 538개 직업 카탈로그 전체를 프롬프트에 넣기 때문에,
# CPU 추론 환경에서는 응답 생성이 몇 분 걸릴 수 있어 넉넉하게 잡는다.
REQUEST_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))


class OllamaError(RuntimeError):
    pass


def chat_json(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    retries: int = 3,
) -> dict:
    """Ollama /api/chat 을 호출하고 응답을 JSON으로 파싱해 돌려준다.

    모델이 설명을 덧붙이는 등 JSON이 아닌 응답을 줄 때가 있어, 파싱에
    실패하면 "JSON만 출력하라"는 보정 메시지를 붙여 재시도한다.
    """
    model = model or OLLAMA_MODEL
    working_messages = list(messages)

    last_error: Exception | None = None
    for _ in range(retries):
        resp = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": model,
                "messages": working_messages,
                "format": "json",
                "stream": False,
                "options": {"temperature": temperature},
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = exc
            working_messages = messages + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "방금 응답은 유효한 JSON이 아니었습니다. "
                        "다른 설명 없이 순수 JSON 객체 하나만 다시 출력하세요."
                    ),
                },
            ]

    raise OllamaError(
        f"Ollama가 {retries}번 시도 후에도 유효한 JSON을 반환하지 않았습니다: {last_error}"
    )

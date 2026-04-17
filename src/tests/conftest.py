# -*- coding: utf-8 -*-
"""
pytest 전역 설정.

이 conftest는 **세 가지 안전망**을 자동으로 적용한다.

  1. sys.path 주입: 프로젝트 루트를 sys.path 맨 앞에 추가해 `src.*` 절대 임포트가
     어느 위치에서 pytest를 실행하든 동작하도록 한다.
  2. FakeProvider monkeypatch: `src.llm.factory.get_llm_provider`를 FakeProvider
     반환 함수로 바꾸어, 모든 `NexusAlphaLLM()` 인스턴스가 네트워크 없이 동작하게
     한다. 에이전트·워크플로우 코드는 수정 없이 그대로 사용 가능.
  3. LangFuse no-op: `LangFuseClient`의 로깅 메서드를 dummy로 치환해 테스트 실행이
     LangFuse 서버를 호출하지 않도록 한다. FakeProvider 차단과 중복 방어.

네트워크 차단 전략(2026-04-17 결정):
    초기 설계에선 pytest-socket `disable_socket()`을 autouse로 적용하려 했으나,
    Windows의 `ProactorEventLoop`가 루프 초기화 시 내부적으로 `socket.socketpair()`를
    사용해 self-pipe를 만드는데, pytest-socket이 소켓 생성 자체를 차단하는 탓에
    `NexusAlphaLLM.call()` → `anyio.run()` 경로가 항상 `SocketBlockedError`로 실패
    했다. 실제 외부 네트워크가 아닌 로컬 파이프까지 막아버리는 부작용이 커서
    pytest-socket autouse는 제거했다. 네트워크 차단은 FakeProvider monkeypatch로
    충분히 달성되며, 향후 Linux 기반 CI에서는 `pytest --disable-socket` 커맨드라인
    플래그로 opt-in 방식으로 재도입한다.

FakeProvider 응답 포맷 결정(2026-04-17):
    CrewAI 1.14.1 `crewai.agents.parser.parse()`는 입력 텍스트에 "Final Answer:"
    문자열이 포함되어 있으면 해당 위치 이후를 Agent의 최종 출력으로 취한다
    (`crewai/agents/constants.py`의 FINAL_ANSWER_ACTION = "Final Answer:"). 따라서
    FakeProvider 기본 응답은 `Thought: ...\nFinal Answer: <텍스트>` 포맷으로 고정
    하여 단일 호출만으로 AgentFinish 경로에 도달하게 한다. CrewAI 메이저/마이너
    업그레이드 시 이 포맷 상수가 바뀔 수 있으므로 requirements.txt에서 버전을 고정한다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.base_provider import BaseLLMProvider  # noqa: E402


DEFAULT_FAKE_FINAL_ANSWER = (
    "Thought: 테스트용 요청을 확인하고 최종 답변을 준비합니다.\n"
    "Final Answer: 이것은 FakeProvider가 반환한 고정 응답입니다."
)


class FakeProvider(BaseLLMProvider):
    """네트워크 호출을 전혀 수행하지 않는 테스트 전용 Provider.

    `BaseLLMProvider.generate()`의 Template Method 계약을 그대로 따르되,
    `_generate_impl()`은 생성자에 주입된 고정 응답 문자열을 비동기 즉시 반환한다.
    반복 호출 이력은 `calls` 리스트에 `(prompt, system)` 튜플로 축적되어 테스트에서
    검증 가능하다.
    """

    def __init__(self, response: Optional[str] = None, model: str = "fake-model-v0") -> None:
        """Args:
            response: 반환할 완성 텍스트. None이면 기본 Final Answer 포맷 사용.
            model: LangFuse 모델 식별자로 기록될 라벨. 기본값으로 충분하다.
        """
        self._response = response if response is not None else DEFAULT_FAKE_FINAL_ANSWER
        self._model = model
        self.calls: list[tuple[str, Optional[str]]] = []

    @property
    def name(self) -> str:
        return "fake"

    def _model_identifier(self) -> str:
        return self._model

    def _extra_log_metadata(self) -> dict[str, Any]:
        return {"fake": True}

    async def _generate_impl(self, prompt: str, system: Optional[str]) -> str:
        self.calls.append((prompt, system))
        return self._response


# ---------------------------------------------------------------------------
# Public fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_provider() -> FakeProvider:
    """기본 Final Answer 응답을 돌려주는 FakeProvider 단일 인스턴스."""
    return FakeProvider()


@pytest.fixture
def fake_provider_factory() -> Callable[..., FakeProvider]:
    """응답 문자열을 커스터마이징한 FakeProvider를 만들어 주는 팩토리.

    각 테스트에서 `p = fake_provider_factory(response="Thought: ...\\nFinal Answer: <원하는 텍스트>")`
    형태로 사용한다.
    """

    def _make(response: Optional[str] = None, model: str = "fake-model-v0") -> FakeProvider:
        return FakeProvider(response=response, model=model)

    return _make


# ---------------------------------------------------------------------------
# Autouse safety net 1 — LLM factory monkeypatch
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _patch_llm_factory(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    """`get_llm_provider`를 FakeProvider 싱글톤으로 치환한다.

    `src.llm.crewai_adapter`는 모듈 탑레벨에서 `from .factory import get_llm_provider`
    로 심볼을 이미 바인딩해 두었기 때문에 `src.llm.factory` 모듈 쪽만 교체해서는
    효과가 없다. 두 네임스페이스 모두 동일한 FakeProvider 인스턴스 반환으로 치환해야
    NexusAlphaLLM이 생성될 때 FakeProvider를 받는다.
    """
    provider = FakeProvider()

    from src.llm import crewai_adapter as adapter_module
    from src.llm import factory as factory_module

    monkeypatch.setattr(factory_module, "get_llm_provider", lambda: provider)
    monkeypatch.setattr(adapter_module, "get_llm_provider", lambda: provider)
    return provider


# ---------------------------------------------------------------------------
# Autouse safety net 2 — LangFuse no-op
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _silence_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """LangFuseClient의 네트워크성 메서드를 모두 no-op으로 만든다."""
    from src.monitoring import langfuse_client as lf_module

    def _noop(self: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ARG001
        return None

    monkeypatch.setattr(lf_module.LangFuseClient, "log_trace", _noop)
    monkeypatch.setattr(lf_module.LangFuseClient, "log_generation", _noop)
    monkeypatch.setattr(lf_module.LangFuseClient, "end_trace", _noop)
    monkeypatch.setattr(lf_module.LangFuseClient, "flush", _noop)


# ---------------------------------------------------------------------------
# 네트워크 차단 — pytest-socket은 Windows 호환 이슈로 autouse 비활성화
# ---------------------------------------------------------------------------
# Windows `ProactorEventLoop`가 루프 초기화 시 `socket.socketpair()`로 self-pipe를
# 만드는데, pytest-socket의 `disable_socket()`은 socket 객체 생성 자체를 막아
# `NexusAlphaLLM.call()` → `anyio.run()` 경로에서 즉시 실패한다. 실제 외부 호출이
# 아닌 로컬 파이프까지 차단하는 부작용이 커서, 네트워크 차단은 FakeProvider
# monkeypatch로 달성하고 pytest-socket은 Linux CI에서만 opt-in(`--disable-socket`)
# 으로 쓴다. 자세한 기록은 docs/progress/phase2_priority1_complete.md 참조.

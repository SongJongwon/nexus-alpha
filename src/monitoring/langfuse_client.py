# -*- coding: utf-8 -*-
"""
LangFuse 모니터링 래퍼 (SDK v4, OpenTelemetry 기반).

- 싱글톤 `LangFuseClient`가 프로세스 전역 LangFuse 세션을 관리한다.
- Provider 레이어에서는 `get_langfuse_client().log_generation(...)` 형태로 호출한다.
- 환경변수(`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`)가
  누락되면 콘솔에 한 번 경고를 출력하고 이후 모든 호출은 조용히 no-op이 된다.
  (모니터링 실패가 메인 기능을 절대 차단하지 않아야 한다.)
- 호스트 환경변수 alias: `LANGFUSE_BASE_URL` (PR #187, Sprint 4). 일부 사용자가
  `BASE_URL` 명칭을 사용한 사례 (LangFuse SDK 문서 mix) 가 silent 미인식으로
  이어지던 결함을 해소한다. `LANGFUSE_HOST` 우선, 미 set 시 `LANGFUSE_BASE_URL`
  fallback.

SDK v4 용어:
    trace        = 최상위 span (as_type="span")
    generation   = LLM 호출 span (as_type="generation")
    observation  = 위 둘의 공통 상위 개념
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Any, Optional


class LangFuseClient:
    """LangFuse SDK v4를 감싸는 싱글톤 클라이언트.

    내부 상태:
        _enabled       : 키가 모두 존재하고 SDK 초기화에 성공했는지.
        _client        : 실제 `langfuse.Langfuse` 인스턴스 (또는 None).
        _current_trace : `log_trace`로 시작된 진행 중 root span (없으면 None).
            동일 trace 안에서 생성된 `log_generation` 호출은 이 span의 자식으로 매달린다.
    """

    _instance: Optional["LangFuseClient"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._enabled: bool = False
        self._client: Any = None
        self._current_trace: Any = None
        self._host: str = _resolve_langfuse_host()

        public_key = _clean_env("LANGFUSE_PUBLIC_KEY")
        secret_key = _clean_env("LANGFUSE_SECRET_KEY")

        if not public_key or not secret_key:
            print(
                "[LangFuse] LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY가 설정되지 "
                "않아 모니터링을 비활성화합니다.",
                file=sys.stderr,
            )
            return

        try:
            from langfuse import Langfuse  # 지연 import

            self._client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=self._host,
            )
            self._enabled = True
        except Exception as exc:  # noqa: BLE001 (모니터링 실패는 메인 경로 차단 금지)
            print(f"[LangFuse] 초기화 실패: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 싱글톤 접근
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "LangFuseClient":
        """프로세스 전역 단일 인스턴스를 반환한다(Thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # 공개 속성
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """LangFuse 전송이 활성화되어 있는지 여부."""
        return self._enabled

    @property
    def host(self) -> str:
        """대시보드 base URL (예: https://cloud.langfuse.com)."""
        return self._host

    def current_trace_id(self) -> Optional[str]:
        """활성화된 root span의 trace id (대시보드 링크용). 없으면 None."""
        if not self._enabled or self._client is None:
            return None
        try:
            return self._client.get_current_trace_id()
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # 로깅 API
    # ------------------------------------------------------------------
    def log_trace(
        self,
        name: str,
        user_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Any:
        """새 trace(root span)를 시작하고 후속 `log_generation`이 그 하위에 매달리도록 한다.

        Returns:
            생성된 LangfuseSpan 객체(비활성화 상태면 None).
        """
        if not self._enabled:
            return None
        try:
            merged_metadata: dict = dict(metadata or {})
            if user_id and "user_id" not in merged_metadata:
                merged_metadata["user_id"] = user_id

            span = self._client.start_observation(
                as_type="span",
                name=name,
                metadata=merged_metadata or None,
            )
            self._current_trace = span
            return span
        except Exception as exc:  # noqa: BLE001
            print(f"[LangFuse] trace 생성 실패: {exc}", file=sys.stderr)
            return None

    def log_generation(
        self,
        name: str,
        input: Any,
        output: Any,
        model: str,
        metadata: Optional[dict] = None,
    ) -> Any:
        """LLM 호출 1건을 Generation observation으로 기록한다.

        현재 trace가 있으면 그 자식으로, 없으면 최상위 generation으로 기록한다.
        항상 입력/출력이 모두 주어진 완성된 이벤트이므로 즉시 `.end()`까지 호출한다.
        """
        if not self._enabled:
            return None
        try:
            parent = self._current_trace if self._current_trace is not None else self._client
            gen = parent.start_observation(
                as_type="generation",
                name=name,
                input=input,
                output=output,
                model=model,
                metadata=metadata or None,
            )
            try:
                gen.end()
            except Exception:  # noqa: BLE001
                pass
            return gen
        except Exception as exc:  # noqa: BLE001
            print(f"[LangFuse] generation 기록 실패: {exc}", file=sys.stderr)
            return None

    def end_trace(self) -> None:
        """현재 trace(root span)를 종료한다. 이후 generation은 독립 기록된다."""
        trace = self._current_trace
        self._current_trace = None
        if trace is None:
            return
        try:
            trace.end()
        except Exception as exc:  # noqa: BLE001
            print(f"[LangFuse] trace 종료 실패: {exc}", file=sys.stderr)

    def flush(self) -> None:
        """버퍼된 이벤트를 즉시 LangFuse 서버로 전송한다."""
        if not self._enabled:
            return
        try:
            self._client.flush()
        except Exception as exc:  # noqa: BLE001
            print(f"[LangFuse] flush 실패: {exc}", file=sys.stderr)


def _clean_env(key: str, default: str = "") -> str:
    """환경변수를 읽어 공백과 감싸는 따옴표를 제거한 값을 반환한다."""
    value = os.getenv(key, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    return value


def _resolve_langfuse_host() -> str:
    """LangFuse 대시보드 호스트 결정.

    우선순위:
        1) ``LANGFUSE_HOST`` (정식 — LangFuse SDK 공식 명칭)
        2) ``LANGFUSE_BASE_URL`` (alias — 일부 사용자가 사용)
        3) 기본 cloud 엔드포인트

    PR #187 — Sprint 4. 두 명칭 다른 ``.env`` 가 silent 미인식으로 이어지던 결함 해소.
    """
    primary = _clean_env("LANGFUSE_HOST")
    if primary:
        return primary
    alias = _clean_env("LANGFUSE_BASE_URL")
    if alias:
        print(
            "[LangFuse] LANGFUSE_BASE_URL 사용 감지 — 정식 명칭 LANGFUSE_HOST 권장. "
            "본 process 에서는 LANGFUSE_BASE_URL 값으로 동작합니다.",
            file=sys.stderr,
        )
        return alias
    return "https://cloud.langfuse.com"


def get_langfuse_client() -> LangFuseClient:
    """싱글톤 `LangFuseClient` 인스턴스를 반환한다."""
    return LangFuseClient.get_instance()

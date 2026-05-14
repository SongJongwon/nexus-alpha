# -*- coding: utf-8 -*-
"""APIKeyProvider 의 max_tokens 기본값 회귀 차단 (PR #135).

배경 (2026-05-14 종합 점검에서 발견):
    [api_key_provider.py:37] 의 ``max_tokens=1024`` 가 Pytest Author 백스토리의
    ``≥1200 chars / ≥10 def test_*`` 요구와 *구조적 충돌* — 매 빌드마다
    ``retry_task_if_short`` 가 트리거되어 빌드 시간 + 비용 2배.

    예: 친구 PC 의 Message_App.exe 빌드 33.11 min 중 ~2 min 이 retry 비용.
    Sonnet 4.6 의 1024 토큰 출력 ≈ ~750자 → Pytest Author 가 요구하는 1200자
    구조적 미달 → 자동 retry → 다시 잘려서 retry → 누적 비용.

PR #135 처방:
    기본값 1024 → 4096 (4배). 4096 토큰 ≈ ~3000자 → Pytest Author + GUI Code
    Generator 요구 안전 충족.

회귀 차단 — 본 테스트가 깨지면 33min 빌드 비용 회귀 + retry 폭증.
"""

from __future__ import annotations

import inspect

from src.llm.api_key_provider import APIKeyProvider


def test_max_tokens_default_is_4096() -> None:
    """``APIKeyProvider.__init__`` 의 ``max_tokens`` 기본값이 4096.

    1024 회귀 시 Pytest Author 의 ``retry_task_if_short`` 가 매 빌드마다 트리거 →
    LLM 호출 비용 + 빌드 시간 2배.
    """
    sig = inspect.signature(APIKeyProvider.__init__)
    max_tokens_param = sig.parameters.get("max_tokens")
    assert max_tokens_param is not None, "max_tokens 파라미터 누락"
    assert max_tokens_param.default == 4096, (
        f"max_tokens 기본값 회귀 — 현재 {max_tokens_param.default}, 기대 4096. "
        "1024 회귀 시 Pytest Author 백스토리 ≥1200 chars 요구와 구조적 충돌."
    )


def test_max_tokens_default_at_least_2048() -> None:
    """미래 변경 시 *최소* 2048 보장 (조정 안전 마진).

    누군가 비용 절감 의도로 기본값을 낮춰도 1024 미만으로는 가지 않도록 floor
    설정. 1024 는 Pytest Author 요구와 충돌이 명확.
    """
    sig = inspect.signature(APIKeyProvider.__init__)
    default = sig.parameters["max_tokens"].default
    assert default >= 2048, (
        f"max_tokens 기본값 {default} 가 2048 미만 — Pytest Author / GUI Code "
        "Generator 의 출력량 요구 (≥1200~1500자) 안전 마진 부족"
    )

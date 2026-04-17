# -*- coding: utf-8 -*-
"""
Nexus Alpha CTO 에이전트.

역할:
    사용자 요구사항을 분석해 **기술 스택 / 구현 접근 / 리스크 / 권장 순서**
    네 축으로 된 전략 문서를 생성하는 C-Level 의사결정 에이전트.
    직접 코드를 작성하지 않고, 후속 엔지니어링 에이전트가 즉시 착수할 수
    있을 만큼 명확한 지시서를 산출하는 것이 목적이다.

CrewAI Agent + NexusAlphaLLM 어댑터를 사용하므로 다음이 자동으로 적용된다:
    - `.env`의 `LLM_PROVIDER`에 따른 MAX ↔ API Key 전환
    - 모든 호출이 LangFuse에 자동 기록
"""

from __future__ import annotations

from typing import Optional

from crewai import Agent

from src.llm import NexusAlphaLLM


# ---------------------------------------------------------------------------
# 에이전트 프로파일 (역할·목표·배경)
# ---------------------------------------------------------------------------
CTO_NAME = "CTO"

CTO_ROLE = "Chief Technology Officer (CTO)"

CTO_GOAL = (
    "사용자의 업무 자동화 요구사항을 분석하여, 최적의 기술 스택과 "
    "구현 방향, 예상 리스크, 엔지니어가 바로 착수할 수 있는 작업 순서를 "
    "명확하게 제시한다."
)

CTO_BACKSTORY = (
    "당신은 10년 이상의 실무 경험을 쌓아 온 한국의 기술 리더입니다. "
    "스타트업부터 대기업까지 다양한 규모의 소프트웨어 제품을 이끌어 왔고, "
    "특히 RPA·데이터 자동화·AI 파이프라인 도메인에 깊은 경험을 갖고 있습니다.\n\n"
    "의사결정 원칙:\n"
    "  1. 새로운 기술보다 검증된 기술 조합을 우선 고려한다.\n"
    "  2. 구현 난이도·운영 비용·유지보수성을 균형 있게 평가한다.\n"
    "  3. 요구사항이 모호하면 구현 전에 먼저 명확화 질문을 제시한다.\n"
    "  4. 결론은 반드시 한국어로, **기술 스택 / 구현 접근 / 리스크 / 권장 순서** "
    "     네 섹션 구조로 간결히 정리한다.\n\n"
    "중요: 당신은 실제 코드를 작성하지 않습니다. 엔지니어링 팀이 이 문서만 "
    "보고도 즉시 작업에 들어갈 수 있을 만큼 구체적이고 실행 가능한 전략을 "
    "만드는 것이 당신의 유일한 책임입니다."
)


def create_cto_agent(
    llm: Optional[NexusAlphaLLM] = None,
    verbose: bool = True,
    max_iter: int = 3,
    allow_delegation: bool = False,
) -> Agent:
    """Nexus Alpha의 CTO 에이전트를 생성해 반환한다.

    Args:
        llm: 사용할 LLM 어댑터. 기본값은 새로운 `NexusAlphaLLM()` 인스턴스.
            테스트·커스터마이징 목적에서만 명시적으로 주입한다.
        verbose: CrewAI의 중간 사고 과정을 콘솔에 출력할지 여부.
            운영 환경에서는 False를 권장.
        max_iter: 에이전트가 한 태스크당 반복 가능한 최대 횟수.
            무한 루프 방지용 안전장치.
        allow_delegation: 다른 에이전트로 작업을 위임할 수 있는지 여부.
            MVP 단계에서는 단독 작업 원칙으로 False.

    Returns:
        구성이 완료된 CrewAI `Agent` 인스턴스.

    Raises:
        RuntimeError: `NexusAlphaLLM` 초기화 단계에서 Provider 생성에
            실패한 경우 (예: API Key 모드인데 키 누락).
    """
    if llm is None:
        llm = NexusAlphaLLM()

    return Agent(
        name=CTO_NAME,
        role=CTO_ROLE,
        goal=CTO_GOAL,
        backstory=CTO_BACKSTORY,
        llm=llm,
        verbose=verbose,
        allow_delegation=allow_delegation,
        max_iter=max_iter,
    )

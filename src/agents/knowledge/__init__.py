# -*- coding: utf-8 -*-
"""
지식 관리(Knowledge) 에이전트 패키지.

사용 예:
    from src.agents.knowledge import (
        create_knowledge_curator_agent,
        create_rag_searcher_agent,
    )

    curator = create_knowledge_curator_agent()
    searcher = create_rag_searcher_agent()
"""

from .curator import (
    KNOWLEDGE_CURATOR_BACKSTORY,
    KNOWLEDGE_CURATOR_GOAL,
    KNOWLEDGE_CURATOR_NAME,
    KNOWLEDGE_CURATOR_ROLE,
    create_knowledge_curator_agent,
)
from .rag_searcher import (
    RAG_SEARCHER_BACKSTORY,
    RAG_SEARCHER_GOAL,
    RAG_SEARCHER_NAME,
    RAG_SEARCHER_ROLE,
    create_rag_searcher_agent,
)

__all__ = [
    "KNOWLEDGE_CURATOR_BACKSTORY",
    "KNOWLEDGE_CURATOR_GOAL",
    "KNOWLEDGE_CURATOR_NAME",
    "KNOWLEDGE_CURATOR_ROLE",
    "RAG_SEARCHER_BACKSTORY",
    "RAG_SEARCHER_GOAL",
    "RAG_SEARCHER_NAME",
    "RAG_SEARCHER_ROLE",
    "create_knowledge_curator_agent",
    "create_rag_searcher_agent",
]

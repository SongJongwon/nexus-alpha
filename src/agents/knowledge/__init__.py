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

from .curate import (
    DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES,
    curate_workflow,
    prune_knowledge_index_lru,
)
from .curator import (
    KNOWLEDGE_CURATOR_BACKSTORY,
    KNOWLEDGE_CURATOR_GOAL,
    KNOWLEDGE_CURATOR_NAME,
    KNOWLEDGE_CURATOR_ROLE,
    create_knowledge_curator_agent,
)
from .documentation import (
    ARCH_REL,
    README_NAME,
    SETUP_REL,
    USAGE_REL,
    DocumentationResult,
    generate_documentation,
)
from .documentation_lead import (
    DOCUMENTATION_LEAD_BACKSTORY,
    DOCUMENTATION_LEAD_GOAL,
    DOCUMENTATION_LEAD_NAME,
    DOCUMENTATION_LEAD_ROLE,
    create_documentation_lead_agent,
)
from .rag_searcher import (
    RAG_SEARCHER_BACKSTORY,
    RAG_SEARCHER_GOAL,
    RAG_SEARCHER_NAME,
    RAG_SEARCHER_ROLE,
    create_rag_searcher_agent,
)
from .recall import format_recalled_entries_for_context, recall_past_entries
from .schemas import VALID_QA_VERDICTS, KnowledgeEntry

__all__ = [
    "ARCH_REL",
    "DEFAULT_KNOWLEDGE_INDEX_MAX_ENTRIES",
    "DOCUMENTATION_LEAD_BACKSTORY",
    "DOCUMENTATION_LEAD_GOAL",
    "DOCUMENTATION_LEAD_NAME",
    "DOCUMENTATION_LEAD_ROLE",
    "DocumentationResult",
    "KNOWLEDGE_CURATOR_BACKSTORY",
    "KNOWLEDGE_CURATOR_GOAL",
    "KNOWLEDGE_CURATOR_NAME",
    "KNOWLEDGE_CURATOR_ROLE",
    "KnowledgeEntry",
    "README_NAME",
    "SETUP_REL",
    "RAG_SEARCHER_BACKSTORY",
    "RAG_SEARCHER_GOAL",
    "RAG_SEARCHER_NAME",
    "RAG_SEARCHER_ROLE",
    "USAGE_REL",
    "VALID_QA_VERDICTS",
    "create_documentation_lead_agent",
    "create_knowledge_curator_agent",
    "create_rag_searcher_agent",
    "curate_workflow",
    "format_recalled_entries_for_context",
    "generate_documentation",
    "prune_knowledge_index_lru",
    "recall_past_entries",
]

# -*- coding: utf-8 -*-
"""
Nexus Alpha 모니터링 패키지.

외부 모듈은 보통 아래만 쓴다:

    from src.monitoring import get_langfuse_client

    client = get_langfuse_client()
    trace = client.log_trace(name="my-trace")
    # ... LLM 호출 ...
    client.flush()
"""

from .langfuse_client import LangFuseClient, get_langfuse_client

__all__ = ["LangFuseClient", "get_langfuse_client"]

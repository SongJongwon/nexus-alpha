# -*- coding: utf-8 -*-
"""
Nexus Alpha 워크플로우 패키지.

사용 예:
    from src.workflows import run_analyze_and_implement

    result = run_analyze_and_implement(
        "매출 Excel을 분석해 PDF 보고서로 만드는 Python 스크립트를 만들어줘"
    )
    print(result.saved_dir)
"""

from .analyze_and_implement import WorkflowResult, run_analyze_and_implement

__all__ = [
    "WorkflowResult",
    "run_analyze_and_implement",
]

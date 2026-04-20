# -*- coding: utf-8 -*-
"""
디자인(Design) 에이전트 패키지 (Phase 4 신설 본부, v4).

`docs/architecture/nexus_alpha_org_v4.md` §3-7 — 3명 정원:
    - GUI Designer: 와이어프레임·레이아웃·인터랙션 흐름 설계
    - GUI Code Generator: UI 사양 → 실제 GUI 코드 생성 (Tkinter/Flet/PyQt6)
    - Theme Designer: 디자인 토큰(palette·typography·spacing) 결정

UI/UX Analyst 는 *분석가* 라 본 본부 아닌 `src/agents/planning/` 에 별도 배치
(관심사 분리: 분석 vs 시각 디자인 생산).

사용 예:
    from src.agents.design import (
        create_gui_code_generator_agent,
        create_gui_designer_agent,
        create_theme_designer_agent,
    )
    designer = create_gui_designer_agent()
    theme = create_theme_designer_agent()
    coder = create_gui_code_generator_agent()
"""

from .gui_code_generator import (
    GUI_CODE_GENERATOR_BACKSTORY,
    GUI_CODE_GENERATOR_GOAL,
    GUI_CODE_GENERATOR_NAME,
    GUI_CODE_GENERATOR_ROLE,
    create_gui_code_generator_agent,
)
from .gui_designer import (
    GUI_DESIGNER_BACKSTORY,
    GUI_DESIGNER_GOAL,
    GUI_DESIGNER_NAME,
    GUI_DESIGNER_ROLE,
    create_gui_designer_agent,
)
from .theme_designer import (
    THEME_DESIGNER_BACKSTORY,
    THEME_DESIGNER_GOAL,
    THEME_DESIGNER_NAME,
    THEME_DESIGNER_ROLE,
    create_theme_designer_agent,
)

__all__ = [
    "GUI_CODE_GENERATOR_BACKSTORY",
    "GUI_CODE_GENERATOR_GOAL",
    "GUI_CODE_GENERATOR_NAME",
    "GUI_CODE_GENERATOR_ROLE",
    "GUI_DESIGNER_BACKSTORY",
    "GUI_DESIGNER_GOAL",
    "GUI_DESIGNER_NAME",
    "GUI_DESIGNER_ROLE",
    "THEME_DESIGNER_BACKSTORY",
    "THEME_DESIGNER_GOAL",
    "THEME_DESIGNER_NAME",
    "THEME_DESIGNER_ROLE",
    "create_gui_code_generator_agent",
    "create_gui_designer_agent",
    "create_theme_designer_agent",
]

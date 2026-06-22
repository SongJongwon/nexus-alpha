# -*- coding: utf-8 -*-
"""v13 P29 — 구조 보존 회귀 게이트(Structural-Preservation Regression Gate) 추출기.

진단 배경(C1): iterate 시 "기존 구조와 식별자(파일명·클래스·함수 시그니처)를 최대한 유지·백지 재작성
금지" 지시가 요청·CTO 설계서까지 정상 주입·수용됐으나, Engineer codegen 이 이를 무시해 데이터모델/
Repository API 를 전면 재작성하고 공개 식별자(클래스·함수·DB 컬럼: node_type·sort_order·멀티프로젝트)를
드롭했다. *산출물을 보존 약속과 대조하는 검사가 없어* build/smoke/QA 를 통과했다. 실패 모드 = 강제
(enforcement) 부재이지 프롬프트 설계 아님.

본 모듈은 *입력(프롬프트)이 아니라 출력(산출 코드)* 의 **공개표면**을 결정론적으로 추출한다(LLM 미사용,
비용 0). iter 간 공개표면 diff 로 정당사유 없는 드롭을 잡는 게이트의 추출 절반을 담당한다. 판정/주입은
``iterative_loop._apply_structural_regression_override`` 가 기존 *_override 패턴으로 수행한다.

공개표면 정의(v1):
    - ``file::<상대경로>``        : 파일 존재 (파일명 보존)
    - ``<파일>::<Class>``          : public 클래스 (밑줄 시작 제외)
    - ``<파일>::<Class>.<method>`` : public 메서드
    - ``<파일>::<func>``           : public 모듈 함수
    - ``<table>::<column>``        : SQL CREATE TABLE 컬럼 (제약/키 라인 제외)

스코프 가드(v1): Python(ast) + SQL(정규식). *이름집합 diff* 만. 미지원 파일타입은 무해 skip(파일 존재만
기록). 시그니처 파라미터 단위 diff·JS/기타 언어 추출기는 명시적 OUT(추후). 파싱 불가/예외는 graceful
(해당 파일의 Python 표면만 생략, 크래시·플래그 없음).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, Set

# SQL CREATE TABLE 의 *컬럼* 추출용. 비탐욕 본문 + 종결 ");" — 다중 테이블은 finditer 로 모두.
# 엣지케이스(v1 한계, 주석): 종결 세미콜론 없는 CREATE TABLE 은 미매칭(graceful skip),
# 본문 내 중첩 괄호(예: NUMERIC(10,2) / REFERENCES t(col))는 *깊이 추적 콤마 분리* 로 보호.
_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?(\w+)[\"'`\]]?\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
# 컬럼이 아니라 *테이블 제약* 을 시작하는 키워드 — 해당 절은 컬럼명으로 집계하지 않음.
_CONSTRAINT_KEYWORDS = frozenset(
    {"primary", "foreign", "unique", "check", "constraint", "key", "index"}
)


def _is_public(name: str) -> bool:
    """밑줄 시작(_x / __x / dunder) = 내부 식별자 → 공개표면 제외."""
    return bool(name) and not name.startswith("_")


def _py_surface(fname: str, text: str) -> Set[str]:
    """``ast`` 로 top-level public 클래스/함수 + 클래스의 public 메서드 추출.

    파싱 불가(truncated / 문법 오류)면 빈 set 반환 — graceful (해당 파일 Python 표면 생략).
    중첩 함수/클래스는 v1 미집계(공개 API 표면은 top-level + 클래스 메서드로 한정).
    """
    out: Set[str] = set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return out  # graceful — 파싱 불가 파일은 Python 표면 미추출(크래시 없음)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_public(node.name):
                out.add(f"{fname}::{node.name}")
        elif isinstance(node, ast.ClassDef):
            if not _is_public(node.name):
                continue
            out.add(f"{fname}::{node.name}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _is_public(item.name):
                        out.add(f"{fname}::{node.name}.{item.name}")
    return out


def _split_top_level(body: str) -> list[str]:
    """괄호 깊이 0 의 콤마로만 분리(REFERENCES t(col) / NUMERIC(10,2) 보호)."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _sql_surface(text: str) -> Set[str]:
    """모든 ``CREATE TABLE`` 에서 ``table::column`` 추출. 제약/키 절은 제외."""
    out: Set[str] = set()
    for m in _CREATE_TABLE_RE.finditer(text or ""):
        table = m.group(1)
        for part in _split_top_level(m.group(2)):
            tokens = part.strip().split()
            if not tokens:
                continue
            col = tokens[0].strip("\"'`[]")
            if not col or col.lower() in _CONSTRAINT_KEYWORDS:
                continue  # 테이블 제약(FOREIGN KEY / PRIMARY KEY …) — 컬럼 아님
            out.add(f"{table}::{col}")
    return out


def extract_public_surface(code_map: Dict[str, str]) -> Set[str]:
    """``{상대파일명: 소스텍스트}`` → 공개표면 집합(결정론, LLM 미사용).

    - ``.py`` : ``file::`` + Python(ast) 표면 + SQL(임베디드 ``_SCHEMA`` 등) 표면.
    - ``.sql``/기타 : ``file::`` + SQL 정규식 표면(매칭 시). 미지원이라도 무해(파일 존재만).
    """
    surface: Set[str] = set()
    for fname, text in code_map.items():
        surface.add(f"file::{fname}")
        if fname.endswith(".py"):
            surface |= _py_surface(fname, text or "")
        surface |= _sql_surface(text or "")  # .py 임베디드 스키마 + .sql 모두 커버
    return surface


def _chain_code_map(chain_result: Any) -> Dict[str, str]:
    """``chain_result.saved_dir/code/*.py`` → ``{파일명: 텍스트}``.

    ``_extract_engineer_output_excerpt`` 와 **동일 소스**(saved_dir/code) — 게이트의 계약이
    Engineer 보존 지시의 계약과 같도록. 단 게이트는 *프롬프트 truncation 없이* 전체 .py 를 읽어
    공개표면 정확도를 확보(드롭 목록이 must-fix 로 자가수정되므로 과대강제는 무해). 실패 → ``{}``.
    """
    if chain_result is None:
        return {}
    saved_dir = getattr(chain_result, "saved_dir", None)
    if saved_dir is None:
        return {}
    try:
        code_dir = Path(saved_dir) / "code"
    except (TypeError, ValueError):
        return {}
    if not code_dir.is_dir():
        return {}
    out: Dict[str, str] = {}
    try:
        for py in sorted(code_dir.glob("*.py")):
            try:
                out[py.name] = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    except OSError:
        return {}
    return out


def surface_from_chain(chain_result: Any) -> Set[str]:
    """``chain_result``(산출) → 공개표면 집합. 추출 불가 → 빈 set(graceful)."""
    return extract_public_surface(_chain_code_map(chain_result))


__all__ = [
    "extract_public_surface",
    "surface_from_chain",
]

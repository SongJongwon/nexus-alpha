# -*- coding: utf-8 -*-
"""v13 P30 — prev-code 발췌 한도 확대(15_000 → 120_000) 회귀 test.

진단(P30): ``_build_prev_code_context`` 의 ``max_chars=15_000`` 하드코딩이 직전 코드를 알파벳·크기순으로
잘라, WBS 런(10파일/63,618자)에서 7파일(~76% — pms_models.Node·pms_rollup·pms_ui 등)을 Engineer 가
*못 봐* 보존이 구조적으로 불가 → 전면 재작성 유발. 15k 는 근거 없는 임의값(모델 컨텍스트 ≥200k 토큰).
P30 = 평면 한도 확대만(순서 공정성·스마트 포함은 OUT — 미입증).

검증:
  - WBS 회귀: 10파일/~64k 픽스처 → 새 한도(120k)로 *10파일 전부* 포함(특히 pms_models·pms_ui).
    동일 픽스처를 옛 한도(15k)로 추출 시 뒤쪽·큰 파일 누락 → 확대가 그 갭을 메움을 대조.
  - 경계: 총 길이 < 120k → 컷 없음(전체). > 120k → 여전히 하드 컷(현 동작 보존), 크래시 없음.
  - 상수/기본값: PREV_CODE_MAX_CHARS == 120_000, _build_prev_code_context 기본값이 그 상수.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from src.workflows.iterative_loop import (
    PREV_CODE_MAX_CHARS,
    _build_prev_code_context,
    _extract_engineer_output_excerpt,
)

# 135755(WBS) 파일명·바이트 분포를 *증류* — 실제 코드를 복사하지 않고 크기만 재현(경로 의존 0).
# sorted(glob) 알파벳 순에서 큰 파일(pms_ui)이 뒤쪽 → 옛 15k 컷의 1순위 탈락 대상.
_WBS_FILE_SIZES = {
    "pms_app.py": 3698,
    "pms_db.py": 11287,
    "pms_models.py": 4034,   # Node 데이터클래스 — 옛 한도서 누락되던 핵심
    "pms_rollup.py": 7364,
    "pms_tree_ops.py": 4262,
    "pms_ui.py": 17749,       # 최대 — 알파벳·크기 양쪽으로 1순위 탈락
    "test_pms_app.py": 7724,
    "test_pms_db.py": 2073,
    "test_pms_rollup.py": 3270,
    "test_pms_tree_ops.py": 2157,
}  # 합계 63,618 (실제와 동일)


def _write_code_dir(tmp_path, sizes: dict) -> SimpleNamespace:
    """tmp_path/code/*.py 를 주어진 바이트 크기로 채우고 chain_result 스텁 반환."""
    code = tmp_path / "code"
    code.mkdir()
    for name, size in sizes.items():
        header = f"# {name}\nIDENT_{name.replace('.', '_')} = 1\n"
        pad = max(0, size - len(header.encode()))
        (code / name).write_text(header + ("# pad line filler\n" * (pad // 18 + 1)), encoding="utf-8")
    return SimpleNamespace(saved_dir=str(tmp_path))


class TestWbsRegression:
    def test_new_budget_includes_all_ten_files(self, tmp_path):
        """새 한도(120k)로 WBS 10파일 전부 발췌에 포함 — 특히 옛 한도서 빠지던 것들."""
        chain = _write_code_dir(tmp_path, _WBS_FILE_SIZES)
        excerpt = _extract_engineer_output_excerpt(chain, max_chars=PREV_CODE_MAX_CHARS)
        for name in _WBS_FILE_SIZES:
            assert f"# {name}" in excerpt, f"{name} 가 발췌에 없음(누락)"
        # 진단상 핵심 누락 파일 2종이 이제 보임
        assert "# pms_models.py" in excerpt and "# pms_ui.py" in excerpt

    def test_old_budget_dropped_them(self, tmp_path):
        """대조: 옛 한도(15k)면 뒤쪽·큰 파일(pms_ui 등) 누락 — 확대가 메운 갭을 입증."""
        chain = _write_code_dir(tmp_path, _WBS_FILE_SIZES)
        old = _extract_engineer_output_excerpt(chain, max_chars=15_000)
        assert "# pms_ui.py" not in old  # 알파벳·크기상 15k 안에 못 들어옴
        assert len(old) <= 15_000 + 200  # 하드 컷 유지

    def test_build_prev_code_context_default_sees_all(self, tmp_path):
        """_build_prev_code_context 기본값(=120k)으로 래핑 발췌에 10파일 전부 + 보존 지시."""
        chain = _write_code_dir(tmp_path, _WBS_FILE_SIZES)
        ctx = _build_prev_code_context(chain, platform_intent="desktop")
        assert "기존 구조와 식별자" in ctx  # 보존 지시(기본 분기) 유지
        for name in _WBS_FILE_SIZES:
            assert f"# {name}" in ctx


class TestBoundary:
    def test_under_budget_no_cut(self, tmp_path):
        """총 길이 < 120k → 컷 없이 전체 포함."""
        chain = _write_code_dir(tmp_path, {"a.py": 5000, "b.py": 6000})
        excerpt = _extract_engineer_output_excerpt(chain, max_chars=PREV_CODE_MAX_CHARS)
        assert "# a.py" in excerpt and "# b.py" in excerpt
        assert len(excerpt) < PREV_CODE_MAX_CHARS  # 컷 안 됨

    def test_over_budget_still_hard_cut_no_crash(self, tmp_path):
        """총 길이 > 120k → 여전히 하드 컷(현 동작 보존), 크래시 없음."""
        big = {f"f{i:02d}.py": 20_000 for i in range(10)}  # 200k > 120k
        chain = _write_code_dir(tmp_path, big)
        excerpt = _extract_engineer_output_excerpt(chain, max_chars=PREV_CODE_MAX_CHARS)
        assert len(excerpt) <= PREV_CODE_MAX_CHARS  # 컷 유지(무한 아님)
        assert "# f00.py" in excerpt  # 앞쪽은 포함

    def test_no_code_dir_graceful(self, tmp_path):
        """saved_dir 만 있고 code/ 없음 → 빈 발췌, 크래시 없음(회귀 0)."""
        assert _extract_engineer_output_excerpt(SimpleNamespace(saved_dir=str(tmp_path))) == ""
        assert _build_prev_code_context(SimpleNamespace(saved_dir=str(tmp_path))) == ""


class TestConstant:
    def test_constant_value(self):
        assert PREV_CODE_MAX_CHARS == 120_000

    def test_default_is_constant(self):
        sig = inspect.signature(_build_prev_code_context)
        assert sig.parameters["max_chars"].default == PREV_CODE_MAX_CHARS

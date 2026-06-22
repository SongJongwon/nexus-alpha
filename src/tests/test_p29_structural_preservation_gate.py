# -*- coding: utf-8 -*-
"""v13 P29 — 구조 보존 회귀 게이트(Structural-Preservation Regression Gate) 회귀 test.

진단(C1): "기존 식별자 유지·백지 재작성 금지" 지시가 요청·CTO 설계서까지 주입·수용됐으나 codegen 이
무시해 데이터모델/Repository API 를 전면 재작성하고 공개 식별자(node_type·sort_order·멀티프로젝트)를
드롭, *산출을 보존 약속과 대조하는 검사 부재* 로 통과함. 본 게이트가 출력 공개표면을 직전 iter 과 대조해
정당사유 없는 드롭을 must-fix 로 강제한다(LLM 미사용 → 비용 0, 풀 파이프라인 미실행).

검증:
  - 추출기(결정론): Python(ast) 클래스/public 함수·메서드 + SQL table::column + file::path.
    private(_) 제외, 파싱불가/비-Python graceful skip.
  - override: positive(드롭→IMPROVE+must-fix) / negative(보존→통과) / persistence(지속 드롭→WARN 강등)
    / cap(예산소진→COMPLETE 유지) / non-COMPLETE·iter1 skip.
  - 135755→144801 회귀 증류 픽스처(prev: node_type 컬럼+sort_order+project 테이블 / new: 제거) → 플래그.
"""

from __future__ import annotations

from src.agents.runtime_verification.structural_preservation_gate import (
    extract_public_surface,
    surface_from_chain,
)
from src.agents.c_level.convergence_judge import (
    BlockedCause,
    GapReport,
    JudgmentDecision,
    Verdict,
)
from src.workflows.iterative_loop import _apply_structural_regression_override


def _complete(must_fix: int = 0) -> JudgmentDecision:
    return JudgmentDecision(
        verdict=Verdict.COMPLETE, blocked_cause=BlockedCause.NONE,
        reason="ok", next_action="", must_fix_count=must_fix,
    )


def _override(prev, new, flagged=None, *, iteration=2, max_iter=5):
    return _apply_structural_regression_override(
        _complete(), prev, new, flagged or [],
        gap=GapReport(iteration=iteration), max_iterations=max_iter,
    )


# =============================================================================
# 1. 추출기 — Python(ast)
# =============================================================================
class TestPySurface:
    SRC = (
        "import os\n"
        "class Repository:\n"
        "    def list_nodes(self):\n        return 1\n"
        "    def _private_helper(self):\n        return 2\n"
        "def connect(path):\n    return path\n"
        "def _hidden():\n    return 0\n"
    )

    def test_classes_and_public_funcs(self):
        s = extract_public_surface({"pms_db.py": self.SRC})
        assert "file::pms_db.py" in s
        assert "pms_db.py::Repository" in s
        assert "pms_db.py::Repository.list_nodes" in s
        assert "pms_db.py::connect" in s

    def test_private_excluded(self):
        s = extract_public_surface({"pms_db.py": self.SRC})
        assert "pms_db.py::Repository._private_helper" not in s
        assert "pms_db.py::_hidden" not in s

    def test_unparseable_python_graceful(self):
        """문법 오류 .py → Python 표면 생략, 크래시 없음(file:: 는 남음)."""
        s = extract_public_surface({"broken.py": "def f(:\n  pass\n"})
        assert s == {"file::broken.py"}  # ast 실패 → 함수 미추출, file 만

    def test_non_python_file_inert(self):
        """비-Python(.txt) → file:: 만(무해 skip)."""
        s = extract_public_surface({"notes.txt": "class X: pass"})
        assert s == {"file::notes.txt"}  # .py 아님 → ast 미적용


# =============================================================================
# 2. 추출기 — SQL CREATE TABLE 컬럼
# =============================================================================
class TestSqlSurface:
    SCHEMA = (
        '_SCHEMA = """\n'
        "CREATE TABLE IF NOT EXISTS nodes (\n"
        "    node_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    parent_id INTEGER,\n"
        "    node_type TEXT NOT NULL DEFAULT 'task',\n"
        "    sort_order INTEGER NOT NULL DEFAULT 0,\n"
        "    FOREIGN KEY (parent_id) REFERENCES nodes(node_id) ON DELETE CASCADE\n"
        ");\n"
        "CREATE TABLE project (id INTEGER PRIMARY KEY, name TEXT, budget REAL);\n"
        '"""\n'
    )

    def test_columns_extracted(self):
        s = extract_public_surface({"pms_db.py": self.SCHEMA})
        assert "nodes::node_id" in s
        assert "nodes::node_type" in s
        assert "nodes::sort_order" in s
        assert "project::id" in s
        assert "project::budget" in s

    def test_constraint_lines_excluded(self):
        """FOREIGN KEY / PRIMARY KEY 등 제약 절은 컬럼으로 집계하지 않음."""
        s = extract_public_surface({"pms_db.py": self.SCHEMA})
        assert not any(c.startswith("nodes::FOREIGN") for c in s)
        assert "nodes::FOREIGN" not in s
        # REFERENCES nodes(node_id) 의 중첩 괄호가 컬럼 분리를 깨지 않음
        assert "nodes::parent_id" in s


# =============================================================================
# 3. override — positive / negative
# =============================================================================
class TestOverridePositiveNegative:
    def test_dropped_public_surface_triggers_improve(self):
        prev = {"f.py::A", "f.py::A.run", "f.py::helper", "t::col_x"}
        new = {"f.py::A", "f.py::A.run"}  # helper + t::col_x 드롭
        decision, flagged = _override(prev, new)
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert "f.py::helper" in decision.next_action
        assert "t::col_x" in decision.next_action
        assert set(flagged) >= {"f.py::helper", "t::col_x"}
        assert decision.must_fix_count >= 2

    def test_preserved_surface_stays_complete(self):
        """공개표면 보존(내부/본문만 변경) → COMPLETE 불변(회귀 0)."""
        surface = {"f.py::A", "f.py::A.run", "f.py::helper"}
        decision, flagged = _override(surface, set(surface))
        assert decision.verdict == Verdict.COMPLETE
        assert flagged == []

    def test_added_surface_not_flagged(self):
        """새 식별자 *추가* 는 드롭 아님 → 통과."""
        prev = {"f.py::A"}
        new = {"f.py::A", "f.py::B", "f.py::A.extra"}
        decision, _ = _override(prev, new)
        assert decision.verdict == Verdict.COMPLETE

    def test_non_complete_decision_untouched(self):
        prev, new = {"f.py::A", "f.py::gone"}, {"f.py::A"}
        improve = JudgmentDecision(Verdict.IMPROVE_NEEDED, BlockedCause.NONE, "x", "y", 1)
        out, flagged = _apply_structural_regression_override(
            improve, prev, new, [], gap=GapReport(iteration=2), max_iterations=5)
        assert out is improve  # COMPLETE 아니면 그대로

    def test_iter1_no_prev_skips(self):
        """prev_surface 없음(iter1/추출불가) → skip(회귀 0)."""
        decision, flagged = _override(None, {"f.py::A"})
        assert decision.verdict == Verdict.COMPLETE
        decision2, _ = _override(set(), {"f.py::A"})
        assert decision2.verdict == Verdict.COMPLETE


# =============================================================================
# 4. override — persistence(진동 방지) / cap
# =============================================================================
class TestOverridePersistenceCap:
    def test_persistent_drop_degraded_to_warning(self):
        """이미 플래그된 드롭이 여전히 드롭 → fresh 없음 → COMPLETE 유지(재트리거 안 함)."""
        prev = {"f.py::A", "f.py::gone"}
        new = {"f.py::A"}
        decision, flagged = _override(prev, new, flagged=["f.py::gone"])
        assert decision.verdict == Verdict.COMPLETE  # 지속=정당화 → 강등
        assert "f.py::gone" in flagged  # 누적 보존

    def test_partial_fresh_still_triggers(self):
        """일부는 지속·일부는 신규 드롭 → 신규가 있으면 IMPROVE."""
        prev = {"f.py::A", "f.py::old_gone", "f.py::new_gone"}
        new = {"f.py::A"}
        decision, flagged = _override(prev, new, flagged=["f.py::old_gone"])
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        assert "f.py::new_gone" in decision.next_action
        assert "f.py::old_gone" not in decision.next_action  # 이미 플래그→재안내 안 함

    def test_cap_reached_keeps_complete(self):
        """예산 소진(iter>=max) → 동작 산출을 구조 사유로 BLOCKED 안 함 → COMPLETE 유지."""
        prev = {"f.py::A", "f.py::gone"}
        new = {"f.py::A"}
        decision, flagged = _override(prev, new, iteration=5, max_iter=5)
        assert decision.verdict == Verdict.COMPLETE
        assert "f.py::gone" in flagged  # 기록은 누적


# =============================================================================
# 5. 135755→144801 회귀 증류 픽스처 (positive 통합)
# =============================================================================
# 직전 iter(N-1) — 타입드 계층(node_type) + sort_order + 멀티프로젝트(project 테이블) + Repository.open/list_projects
_PREV_DB = (
    "# file: pms_db.py\n"
    '_SCHEMA = """\n'
    "CREATE TABLE IF NOT EXISTS project (\n"
    "    id INTEGER PRIMARY KEY, name TEXT NOT NULL, budget REAL NOT NULL DEFAULT 0\n"
    ");\n"
    "CREATE TABLE IF NOT EXISTS node (\n"
    "    id INTEGER PRIMARY KEY,\n"
    "    project_id INTEGER NOT NULL,\n"
    "    parent_id INTEGER,\n"
    "    node_type TEXT NOT NULL DEFAULT 'task',\n"
    "    sort_order INTEGER NOT NULL DEFAULT 0,\n"
    "    name TEXT NOT NULL\n"
    ");\n"
    '"""\n'
    "class Repository:\n"
    "    def open(cls, db_path, seed=True):\n        return None\n"
    "    def list_projects(self):\n        return []\n"
    "    def add_node(self, project_id, parent_id, name, node_type):\n        return 1\n"
)
# 현재 iter(N) — 단일프로젝트·무타입 제네릭 트리로 전면 재작성 (node_type/sort_order/project 드롭)
_NEW_DB = (
    "# file: pms_db.py\n"
    '_SCHEMA = """\n'
    "CREATE TABLE IF NOT EXISTS nodes (\n"
    "    node_id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
    "    parent_id INTEGER,\n"
    "    task_name TEXT NOT NULL\n"
    ");\n"
    '"""\n'
    "class Repository:\n"
    "    def list_nodes(self):\n        return []\n"
    "    def add_node(self, parent_id, task_name):\n        return 1\n"
)


class TestRealRegressionFixture:
    def test_gate_flags_135755_to_144801_regression(self):
        prev = extract_public_surface({"pms_db.py": _PREV_DB})
        new = extract_public_surface({"pms_db.py": _NEW_DB})
        decision, flagged = _override(prev, new)
        assert decision.verdict == Verdict.IMPROVE_NEEDED
        dropped = set(flagged)
        # 실제 회귀의 핵심: 타입드 계층(node_type) + sort_order + 멀티프로젝트(project::*) 소멸
        assert "node::node_type" in dropped
        assert "node::sort_order" in dropped
        assert "project::id" in dropped
        # Repository.open / list_projects 식별자 드롭도 포착
        assert "pms_db.py::Repository.open" in dropped
        assert "pms_db.py::Repository.list_projects" in dropped
        # 복원 must-fix 본문에 실제 드롭이 적시됨
        assert "node::node_type" in decision.next_action

    def test_must_fix_only_change_preserves_surface(self):
        """negative — 공개표면(스키마·클래스·시그니처) 유지하고 함수 본문만 고치면 플래그 0."""
        prev = extract_public_surface({"pms_db.py": _NEW_DB})
        # 동일 표면, list_nodes 본문만 변경
        patched = _NEW_DB.replace("    def list_nodes(self):\n        return []",
                                  "    def list_nodes(self):\n        return self._fetch()")
        new = extract_public_surface({"pms_db.py": patched})
        decision, flagged = _override(prev, new)
        assert decision.verdict == Verdict.COMPLETE
        assert flagged == []


# =============================================================================
# 6. surface_from_chain — graceful (chain_result 없음/saved_dir 없음)
# =============================================================================
class TestSurfaceFromChain:
    def test_none_and_missing_graceful(self):
        from types import SimpleNamespace

        assert surface_from_chain(None) == set()
        assert surface_from_chain(SimpleNamespace(saved_dir=None)) == set()
        assert surface_from_chain(SimpleNamespace(saved_dir="/no/such/dir/xyz")) == set()

    def test_reads_code_dir(self, tmp_path):
        from types import SimpleNamespace

        code = tmp_path / "code"
        code.mkdir()
        (code / "m.py").write_text("class A:\n    def run(self):\n        return 1\n", encoding="utf-8")
        s = surface_from_chain(SimpleNamespace(saved_dir=str(tmp_path)))
        assert "file::m.py" in s
        assert "m.py::A" in s and "m.py::A.run" in s

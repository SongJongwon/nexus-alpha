# -*- coding: utf-8 -*-
"""PR #140 Phase 3 — curate_workflow 단위 테스트.

배경: Knowledge Curator 가 워크플로 종료 시 ``KnowledgeEntry`` 산출 → 분산
(workflow_dir/knowledge_entry.yaml) + 중앙 (knowledge_index/<wid>.yaml) 저장.
다음 빌드 진입 시 recall_past_entries 가 검색.

본 테스트 목적:
    - 결정론 산출 (LLM 없이): workflow_id / curated_at / artifacts / verdict 추출
    - QA verdict 결정론 추출: 04_qa_review.md 의 ``Final Answer: APPROVED/NEEDS_REVISION``
    - LLM 합성: summary + tags 채움 (mock 주입)
    - 디스크 저장: 분산 + 중앙 인덱스 둘 다
    - 실패 격리: LLM 예외 시 결정론 entry 만 반환
    - pytest 환경 자동 LLM skip
"""

from __future__ import annotations

from pathlib import Path

from src.agents.knowledge import KnowledgeEntry, curate_workflow


def _create_workflow_dir(
    tmp: Path,
    qa_verdict_text: str = "APPROVED",
    name: str = "workflow_20260515_120000",
) -> Path:
    """가짜 workflow 디렉터리 생성 — 5 파일 + code/ 디렉터리."""
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "00_user_request.txt").write_text("환율 변환기 만들어줘", encoding="utf-8")
    (d / "01_cto_strategy.md").write_text("# CTO\nfrankfurter API", encoding="utf-8")
    (d / "02_analyst_brief.md").write_text("# Analyst\nrequirements", encoding="utf-8")
    (d / "03_engineer_output.md").write_text(
        "# Engineer\n```python\ndef main():\n    pass\n```",
        encoding="utf-8",
    )
    (d / "04_qa_review.md").write_text(
        f"# QA review\n... 본문 ...\nFinal Answer: {qa_verdict_text}",
        encoding="utf-8",
    )
    code_dir = d / "code"
    code_dir.mkdir(exist_ok=True)
    (code_dir / "main.py").write_text("print('hi')", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# 1. 결정론 산출 — LLM 없이도 entry 완성도
# ---------------------------------------------------------------------------


def test_curate_workflow_returns_entry_with_workflow_id(tmp_path: Path) -> None:
    """workflow_id = 디렉터리 이름."""
    workflow_dir = _create_workflow_dir(tmp_path)
    entry, _, _ = curate_workflow(
        workflow_dir, "환율 변환기 만들어줘"
    )
    assert isinstance(entry, KnowledgeEntry)
    assert entry.workflow_id == workflow_dir.name


def test_curate_workflow_extracts_qa_verdict_from_review(tmp_path: Path) -> None:
    """04_qa_review.md 의 Final Answer: APPROVED 자동 추출."""
    workflow_dir = _create_workflow_dir(tmp_path, qa_verdict_text="APPROVED")
    entry, _, _ = curate_workflow(workflow_dir, "x")
    assert entry.qa_verdict == "APPROVED"


def test_curate_workflow_extracts_needs_revision_verdict(tmp_path: Path) -> None:
    """NEEDS_REVISION verdict 도 정상 추출."""
    workflow_dir = _create_workflow_dir(tmp_path, qa_verdict_text="NEEDS_REVISION")
    entry, _, _ = curate_workflow(workflow_dir, "x")
    assert entry.qa_verdict == "NEEDS_REVISION"


def test_curate_workflow_uses_verdict_hint_when_provided(tmp_path: Path) -> None:
    """qa_verdict_hint 가 04_qa_review.md 추출보다 우선."""
    workflow_dir = _create_workflow_dir(tmp_path, qa_verdict_text="NEEDS_REVISION")
    entry, _, _ = curate_workflow(
        workflow_dir, "x", qa_verdict_hint="APPROVED"
    )
    assert entry.qa_verdict == "APPROVED"


def test_curate_workflow_truncates_user_request_oneline(tmp_path: Path) -> None:
    """user_request_oneline 80자 cap."""
    workflow_dir = _create_workflow_dir(tmp_path)
    long_request = "환율" * 100
    entry, _, _ = curate_workflow(workflow_dir, long_request)
    assert len(entry.user_request_oneline) <= 80


def test_curate_workflow_collects_artifacts(tmp_path: Path) -> None:
    """artifacts 목록에 5 핵심 파일 + code/main.py."""
    workflow_dir = _create_workflow_dir(tmp_path)
    entry, _, _ = curate_workflow(workflow_dir, "x")
    assert "00_user_request.txt" in entry.artifacts
    assert "04_qa_review.md" in entry.artifacts
    assert any(a.startswith("code/") for a in entry.artifacts)


def test_curate_workflow_in_pytest_skips_llm_summary(tmp_path: Path) -> None:
    """pytest 환경 + llm_call=None → summary/tags 빈 채로 (결정론만)."""
    workflow_dir = _create_workflow_dir(tmp_path)
    entry, _, _ = curate_workflow(workflow_dir, "환율 변환기")
    assert entry.summary == ""
    assert entry.tags == []


# ---------------------------------------------------------------------------
# 2. 디스크 저장 — 분산 + 중앙 인덱스
# ---------------------------------------------------------------------------


def test_curate_workflow_writes_distributed_yaml(tmp_path: Path) -> None:
    """workflow_dir/knowledge_entry.yaml 작성."""
    workflow_dir = _create_workflow_dir(tmp_path)
    _, dist_path, _ = curate_workflow(workflow_dir, "x")
    assert dist_path == workflow_dir / "knowledge_entry.yaml"
    assert dist_path.exists()
    content = dist_path.read_text(encoding="utf-8")
    assert "workflow_id" in content


def test_curate_workflow_writes_central_index_when_dir_given(tmp_path: Path) -> None:
    """knowledge_index_dir 지정 시 ``<idx>/<wid>.yaml`` 작성."""
    workflow_dir = _create_workflow_dir(tmp_path)
    index_dir = tmp_path / "knowledge_index"
    _, _, idx_path = curate_workflow(
        workflow_dir, "x", knowledge_index_dir=index_dir
    )
    assert idx_path is not None
    assert idx_path.exists()
    assert idx_path.name == f"{workflow_dir.name}.yaml"


def test_curate_workflow_skips_central_index_when_dir_none(tmp_path: Path) -> None:
    """knowledge_index_dir=None 시 중앙 인덱스 미작성."""
    workflow_dir = _create_workflow_dir(tmp_path)
    _, _, idx_path = curate_workflow(workflow_dir, "x")
    assert idx_path is None


# ---------------------------------------------------------------------------
# 3. LLM 합성 — summary + tags 채움
# ---------------------------------------------------------------------------


def test_curate_workflow_uses_injected_llm_for_summary(tmp_path: Path) -> None:
    """``llm_call`` 주입 시 summary/tags 채워짐."""
    workflow_dir = _create_workflow_dir(tmp_path)

    def fake_llm(prompt: str) -> str:
        return (
            '{"summary": "frankfurter API + tkinter 환율 변환기", '
            '"tags": ["currency-converter", "python", "tkinter", "qa-approved"]}'
        )

    entry, _, _ = curate_workflow(
        workflow_dir, "환율 변환기", llm_call=fake_llm
    )
    assert "frankfurter" in entry.summary
    assert "python" in entry.tags
    assert "qa-approved" in entry.tags


def test_curate_workflow_caps_tags_at_5(tmp_path: Path) -> None:
    """tags 5개 이내 cap — LLM 이 더 많이 줘도 자름."""
    workflow_dir = _create_workflow_dir(tmp_path)

    def fake_llm(prompt: str) -> str:
        return (
            '{"summary": "x", "tags": ["a", "b", "c", "d", "e", "f", "g"]}'
        )

    entry, _, _ = curate_workflow(workflow_dir, "x", llm_call=fake_llm)
    assert len(entry.tags) <= 5


def test_curate_workflow_caps_summary_at_120(tmp_path: Path) -> None:
    """summary 120자 이내 cap."""
    workflow_dir = _create_workflow_dir(tmp_path)
    long_summary = "x" * 500

    def fake_llm(prompt: str) -> str:
        return f'{{"summary": "{long_summary}", "tags": []}}'

    entry, _, _ = curate_workflow(workflow_dir, "x", llm_call=fake_llm)
    assert len(entry.summary) <= 120


def test_curate_workflow_survives_llm_exception(tmp_path: Path) -> None:
    """LLM 예외 시 결정론 entry 만 반환 — 워크플로 차단 X."""
    workflow_dir = _create_workflow_dir(tmp_path)

    def boom(prompt: str) -> str:
        raise RuntimeError("LLM error")

    entry, dist_path, _ = curate_workflow(workflow_dir, "x", llm_call=boom)
    assert entry.summary == ""
    assert entry.tags == []
    # 디스크 저장은 정상 완료
    assert dist_path.exists()


def test_curate_workflow_survives_malformed_llm_json(tmp_path: Path) -> None:
    """LLM 이 깨진 JSON 반환 시 결정론 entry 만 반환."""
    workflow_dir = _create_workflow_dir(tmp_path)

    def garbage(prompt: str) -> str:
        return "정말 그냥 자연어 응답 — JSON 아님"

    entry, _, _ = curate_workflow(workflow_dir, "x", llm_call=garbage)
    assert entry.summary == ""
    assert entry.tags == []

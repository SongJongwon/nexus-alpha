# -*- coding: utf-8 -*-
"""v13 P27 — Documentation Lead (본부5) 문서 생성 회귀 test.

목표(진짜 가치 한정): 코드/빌드가 안정된 단계에서 실 산출물(생성 코드 + P25 단일 실행 계약)을 읽어
셋업·실행·사용·구조 문서를 산출물에 묶어 생산. **코드/계약에 실재하는 것만**(환각 0), P25 README
중복 시 검증·보강, 진짜 가치 없으면 skip. 비차단(verdict 불관여) + 개입/P20~P26/web·none·desktop 불변.

검증:
  - web/desktop/none 별 정확한 셋업·실행 문서 + P25 _README_RUN_RE 호환.
  - 정확성: 실재 package.json scripts/진입점만 — 없는 명령 발명 금지(정직한 warning).
  - 중복 회피: 기존 README(유효 실행 명령·우리 마커 없음) → 덮어쓰지 않고 docs/ 보강.
  - 결정론: 같은 입력 → 같은 출력(재현). LLM 보강은 주입 가능 + pytest 자동 skip.
  - 노드: 안정 산출물 부재 → 정직 skip, 예외 silent(비차단), verdict 키 미반환. 그래프/telemetry 배선.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from src.agents.knowledge import (
    DocumentationResult,
    create_documentation_lead_agent,
    generate_documentation,
)
from src.agents.knowledge.documentation import (
    ARCH_REL,
    README_NAME,
    SETUP_REL,
    USAGE_REL,
    _GENERATED_MARKER,
)

# P25 게이트의 실제 README 검사기 — 생성 문서가 진짜로 P25 정규식을 통과하는지 교차검증(P25 코드 미수정).
from src.agents.runtime_verification.packageability_gate import _has_readme_run_command


def _web_pkg(scripts: dict, name: str = "todo-app", desc: str = "할 일 관리 앱", deps: Optional[dict] = None) -> str:
    return json.dumps({
        "name": name, "description": desc, "scripts": scripts,
        "dependencies": deps or {"express": "^4", "react": "^18"},
    })


def _make_web(tmp: Path, scripts: dict, *, server: str = "const app=require('express')(); app.listen(3000);") -> Path:
    d = tmp
    (d / "package.json").write_text(_web_pkg(scripts), encoding="utf-8")
    if server:
        (d / "server.js").write_text(server, encoding="utf-8")
    return d


# =============================================================================
# 1. web — 셋업·실행·사용·구조 + P25 호환
# =============================================================================
class TestWeb:
    def test_generates_all_docs(self, tmp_path: Path) -> None:
        _make_web(tmp_path, {"start": "node server.js", "test": "vitest"})
        r = generate_documentation(tmp_path, build_target="web", user_request="할 일 관리")
        assert r.success and r.status == "generated"
        assert set(r.generated_files) == {README_NAME, USAGE_REL, ARCH_REL}
        assert (tmp_path / README_NAME).is_file()
        assert (tmp_path / USAGE_REL).is_file()
        assert (tmp_path / ARCH_REL).is_file()

    def test_run_command_from_real_package_json(self, tmp_path: Path) -> None:
        """실재 scripts.start → `npm start` (발명 아님). 생성 README 가 P25 검사 통과."""
        _make_web(tmp_path, {"start": "node server.js"})
        r = generate_documentation(tmp_path, build_target="web")
        assert r.run_command == "npm start"
        assert _has_readme_run_command(tmp_path) is True  # P25(미수정) 정규식 호환

    def test_passes_p25_readme_check(self, tmp_path: Path) -> None:
        """생성 README 가 P25 게이트의 _has_readme_run_command 를 *실제로* 통과."""
        _make_web(tmp_path, {"start": "node server.js"})
        generate_documentation(tmp_path, build_target="web")
        assert _has_readme_run_command(tmp_path) is True

    def test_detects_listen_port(self, tmp_path: Path) -> None:
        _make_web(tmp_path, {"start": "node server.js"}, server="app.listen(8787)")
        r = generate_documentation(tmp_path, build_target="web")
        assert r.facts.get("listen_port") == 8787
        assert "8787" in (tmp_path / README_NAME).read_text(encoding="utf-8")

    def test_run_contract_is_authority(self, tmp_path: Path) -> None:
        """P25 PackageabilityResult.command 가 있으면 *검증된 명령* 을 권위로 사용(비-npm 구체 명령)."""
        _make_web(tmp_path, {"start": "node server.js"})
        contract = SimpleNamespace(command="node dist/server.js", extras={"listen_port": 4000})
        r = generate_documentation(tmp_path, build_target="web", run_contract=contract)
        assert r.run_command == "node dist/server.js"
        assert r.facts.get("run_source") == "deployability_gate"

    def test_contract_npm_form_must_exist_in_scripts(self, tmp_path: Path) -> None:
        """적대 리뷰 P27 R1 — npm 형 계약 명령이 package.json scripts 에 *없으면* 환각 금지.

        실재 안 하는 명령을 *실행 가능 명령으로 채택/기술* 하지 않는다(비고에 '무효 처리' 설명 언급은 정직).
        """
        _make_web(tmp_path, {"build": "vite build"})  # start 없음
        contract = SimpleNamespace(command="npm run production", extras={})  # 실재 안 하는 스크립트
        r = generate_documentation(tmp_path, build_target="web", run_contract=contract)
        assert r.run_command == ""  # 발명 명령 미채택(빈 명령)
        readme = (tmp_path / README_NAME).read_text(encoding="utf-8")
        # 실행 섹션이 코드펜스로 그 명령을 *실행 가능* 하게 제시하지 않음(펜스 내부에 미포함).
        fenced = "".join(readme.split("```")[1::2])
        assert "npm run production" not in fenced
        assert "확인하지 못" in readme  # 명령 미확정을 정직히 표기
        assert r.warnings  # 정직한 무효 처리 안내

    def test_contract_npm_form_valid_script_accepted(self, tmp_path: Path) -> None:
        """npm 형 계약 명령이라도 실재 스크립트면 그대로 채택(정상 경로)."""
        _make_web(tmp_path, {"start": "node server.js", "serve": "node server.js"})
        contract = SimpleNamespace(command="npm run serve", extras={})
        r = generate_documentation(tmp_path, build_target="web", run_contract=contract)
        assert r.run_command == "npm run serve"

    def test_contract_token_edge_cases(self, tmp_path: Path) -> None:
        """적대 리뷰 P27 R2 — 토큰 단위 계약 검증: bare/모호/대소문자/패키지매니저/직접 런처."""
        from src.agents.knowledge.documentation import _validate_contract_command

        scripts = {"start": "node server.js", "dev": "vite"}
        ok = lambda c: _validate_contract_command(c, scripts)
        # bare npm / npm run / 다중 인자 → 무효
        assert ok("npm")[0] is False
        assert ok("npm run")[0] is False
        assert ok("npm a b")[0] is False
        # 미실재 스크립트 → 무효
        assert ok("npm run production")[0] is False
        # 실재 스크립트 → 유효, 패키지매니저명·run 소문자 canonical
        assert ok("npm start") == (True, "", "npm start")
        assert ok("NPM start") == (True, "", "npm start")  # 매니저명 소문자 정규화
        assert ok("npm run dev") == (True, "", "npm run dev")
        assert ok("npm RUN dev") == (True, "", "npm run dev")  # run 키워드 정규화
        # yarn/pnpm 동일 규칙
        assert ok("yarn start")[0] is True
        assert ok("pnpm run dev")[0] is True
        # 직접 런처(node/python) + 파일 → 유효(확장자 무관), 런처 단독 → 무효
        assert ok("node server")[0] is True  # 확장자 없어도 파일 인자면 OK
        assert ok("node server.js")[2] == "node server.js"  # 경로 원형 보존
        assert ok("node")[0] is False
        # 미상 형식 → 무효(환각 방지)
        assert ok("frobnicate the_widget")[0] is False
        assert ok("")[0] is False

    def test_contract_script_match_case_sensitive(self, tmp_path: Path) -> None:
        """적대 리뷰 P27 R3 — npm 스크립트명은 case-sensitive: `npm build`↔`Build` 거짓 수용 금지."""
        from src.agents.knowledge.documentation import _validate_contract_command

        caps = {"Build": "vite build"}
        assert _validate_contract_command("npm build", caps)[0] is False  # 'build' != 'Build'
        # 정확 일치 → 유효, canonical 은 *실제 키* 대소문자 보존(런타임 실패 방지)
        assert _validate_contract_command("npm run Build", caps) == (True, "", "npm run Build")


# =============================================================================
# 2. desktop / none
# =============================================================================
class TestDesktopNone:
    def test_desktop_documents_exe(self, tmp_path: Path) -> None:
        (tmp_path / "MyApp.exe").write_bytes(b"MZ")
        r = generate_documentation(tmp_path, build_target="desktop", exe_name="MyApp.exe")
        assert r.run_command == "MyApp.exe"
        readme = (tmp_path / README_NAME).read_text(encoding="utf-8")
        assert "MyApp.exe" in readme
        assert "npm" not in readme  # desktop 에 web 명령 환각 금지

    def test_none_documents_python_entry(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("if __name__ == '__main__': pass", encoding="utf-8")
        (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
        r = generate_documentation(tmp_path, build_target="none")
        assert r.run_command == "python main.py"
        readme = (tmp_path / README_NAME).read_text(encoding="utf-8")
        assert "pip install -r requirements.txt" in readme
        assert "python main.py" in readme

    def test_none_detects_main_guard_file(self, tmp_path: Path) -> None:
        (tmp_path / "weird_entry.py").write_text("def go():\n    pass\n\nif __name__ == '__main__':\n    go()\n", encoding="utf-8")
        r = generate_documentation(tmp_path, build_target="none")
        assert r.run_command == "python weird_entry.py"


# =============================================================================
# 3. 정확성 — 환각 금지
# =============================================================================
class TestAccuracy:
    def test_no_package_json_no_invented_command(self, tmp_path: Path) -> None:
        """package.json 없음 → `npm start` 발명 금지 + 정직한 warning."""
        (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
        r = generate_documentation(tmp_path, build_target="web")
        assert r.run_command == ""  # 발명 0
        assert any("실행" in w or "스크립트" in w for w in r.warnings)
        readme = (tmp_path / README_NAME).read_text(encoding="utf-8")
        assert "npm start" not in readme  # 없는 명령을 적지 않음

    def test_dev_only_scripts_flagged_not_faked(self, tmp_path: Path) -> None:
        """start 부재·dev 만 있으면 dev 를 발명된 start 로 바꾸지 않고 정직 기술."""
        _make_web(tmp_path, {"dev": "vite", "build": "vite build"})
        r = generate_documentation(tmp_path, build_target="web")
        # start 가 없으므로 npm start 를 만들지 않음 — 가용 스크립트로 축소 + warning.
        assert r.run_command != "npm start"
        assert r.warnings

    def test_facts_reflect_real_deps(self, tmp_path: Path) -> None:
        _make_web(tmp_path, {"start": "node server.js"}, server="app.listen(3000)")
        r = generate_documentation(tmp_path, build_target="web")
        assert "express" in r.facts.get("dependencies", [])


# =============================================================================
# 4. 중복 회피 (검증·보강)
# =============================================================================
class TestDedup:
    """적대 리뷰 P27 R2/R3 — 정규식·마커·길이임계 판정 폐기. 불변식: *비어있지 않은 README 는 절대
    덮어쓰지 않는다*(데이터 손실 방지). 보존 시 docs/SETUP.md 로 정확한 셋업·실행 보강. 공백/부재만 생성."""

    def test_nonempty_user_readme_preserved(self, tmp_path: Path) -> None:
        """비어있지 않은 사용자 README → 덮어쓰지 않고 보존(augment) + docs/SETUP.md 로 보강."""
        _make_web(tmp_path, {"start": "node server.js"})
        original = "# 손으로 쓴 README\n\n특별한 안내문.\n"
        (tmp_path / README_NAME).write_text(original, encoding="utf-8")
        r = generate_documentation(tmp_path, build_target="web")
        assert r.status == "augmented"
        assert README_NAME not in r.generated_files  # README 미덮어쓰기
        assert (tmp_path / README_NAME).read_text(encoding="utf-8") == original  # 원문 보존
        assert SETUP_REL in r.generated_files  # 정확한 셋업·실행은 docs/SETUP.md 로
        assert "npm start" in (tmp_path / SETUP_REL).read_text(encoding="utf-8")
        assert (tmp_path / USAGE_REL).is_file()

    def test_readme_with_marker_string_not_clobbered(self, tmp_path: Path) -> None:
        """적대 리뷰 P27 R3 — 사용자 README 가 우연히 우리 마커 문자열을 포함해도 *덮어쓰지 않음*(데이터 손실 0)."""
        _make_web(tmp_path, {"start": "node server.js"})
        sneaky = f"# 내 문서\n\n이 프로젝트는 {_GENERATED_MARKER} 마커를 설명합니다. 사용자 내용.\n"
        (tmp_path / README_NAME).write_text(sneaky, encoding="utf-8")
        r = generate_documentation(tmp_path, build_target="web")
        assert r.status == "augmented"  # 마커 substring 거짓양성으로 클로버 안 됨
        assert (tmp_path / README_NAME).read_text(encoding="utf-8") == sneaky  # 원문 보존

    def test_empty_readme_generated(self, tmp_path: Path) -> None:
        """공백뿐 README → 보존 가치 없음 → 정확한 README 생성(내용 손실 없음)."""
        _make_web(tmp_path, {"start": "node server.js"})
        (tmp_path / README_NAME).write_text("   \n\n", encoding="utf-8")  # 공백뿐
        r = generate_documentation(tmp_path, build_target="web")
        assert r.status == "generated"
        assert README_NAME in r.generated_files
        assert _GENERATED_MARKER in (tmp_path / README_NAME).read_text(encoding="utf-8")  # 생성 마커(provenance)

    def test_rerun_preserves_own_readme_no_clobber(self, tmp_path: Path) -> None:
        """재실행 — 첫 회 생성 README 도 비어있지 않으니 보존(클로버 0). docs/는 결정론 갱신."""
        _make_web(tmp_path, {"serve": "node server.js"})  # start 없음, serve 만
        r1 = generate_documentation(tmp_path, build_target="web")
        assert r1.run_command == "npm run serve" and r1.status == "generated"
        readme1 = (tmp_path / README_NAME).read_text(encoding="utf-8")
        # 재실행 → README 비어있지 않음 → 보존(augment), 원문 그대로(클로버 0)
        r2 = generate_documentation(tmp_path, build_target="web")
        assert r2.status == "augmented"
        assert (tmp_path / README_NAME).read_text(encoding="utf-8") == readme1

    def test_status_skipped_when_core_doc_write_fails(self, tmp_path: Path, monkeypatch) -> None:
        """적대 리뷰 P27 R4 — 핵심 문서(보존 모드=docs/SETUP) 기록 실패 시 status/success 정합(skipped/False)."""
        import src.agents.knowledge.documentation as doc

        _make_web(tmp_path, {"start": "node server.js"})
        (tmp_path / README_NAME).write_text("# 사용자\n\n내용.\n", encoding="utf-8")  # preserve 모드
        real = doc._safe_write

        def fail_setup(path, content, *, parent=None):
            if str(path).endswith("SETUP.md"):
                return False  # SETUP 기록 실패 시뮬
            return real(path, content, parent=parent)

        monkeypatch.setattr(doc, "_safe_write", fail_setup)
        r = doc.generate_documentation(tmp_path, build_target="web")
        assert r.status == "skipped" and r.success is False  # 핵심 문서 실패 → 정직히 skipped


# =============================================================================
# 5. skip(진짜 가치 없음) + 결정론
# =============================================================================
class TestSkipAndDeterminism:
    def test_missing_code_dir_skips(self, tmp_path: Path) -> None:
        r = generate_documentation(tmp_path / "nope", build_target="web")
        assert r.status == "skipped" and not r.success

    def test_deterministic_output(self, tmp_path: Path) -> None:
        """같은 입력 → 같은 문서(재현). 타임스탬프 등 비결정 요소 미포함."""
        _make_web(tmp_path, {"start": "node server.js"}, server="app.listen(3000)")
        generate_documentation(tmp_path, build_target="web")
        readme1 = (tmp_path / README_NAME).read_text(encoding="utf-8")
        usage1 = (tmp_path / USAGE_REL).read_text(encoding="utf-8")
        generate_documentation(tmp_path, build_target="web")  # 재생성
        assert (tmp_path / README_NAME).read_text(encoding="utf-8") == readme1
        assert (tmp_path / USAGE_REL).read_text(encoding="utf-8") == usage1


# =============================================================================
# 6. LLM 보강 (주입 가능 + pytest skip)
# =============================================================================
class TestLLMEnrichment:
    def test_injected_llm_overview_used(self, tmp_path: Path) -> None:
        _make_web(tmp_path, {"start": "node server.js"})
        called = {}

        def fake_llm(prompt: str) -> str:
            called["yes"] = True
            return "이 앱은 할 일을 관리하는 웹 애플리케이션입니다."

        generate_documentation(tmp_path, build_target="web", llm_call=fake_llm)
        assert called.get("yes")
        usage = (tmp_path / USAGE_REL).read_text(encoding="utf-8")
        assert "할 일을 관리하는 웹" in usage

    def test_llm_failure_falls_back(self, tmp_path: Path) -> None:
        _make_web(tmp_path, {"start": "node server.js"})

        def boom(prompt: str) -> str:
            raise RuntimeError("llm down")

        r = generate_documentation(tmp_path, build_target="web", llm_call=boom)
        assert r.success  # 결정론 문서는 그대로 생성(보강 실패 비차단)

    def test_pytest_auto_skips_default_llm(self, tmp_path: Path) -> None:
        """llm_call=None + pytest 환경 → 기본 LLM 호출 안 함(결정론만)."""
        _make_web(tmp_path, {"start": "node server.js"})
        r = generate_documentation(tmp_path, build_target="web")  # llm_call 미주입
        assert r.success  # 결정론 경로로 성공(LLM 미호출)


# =============================================================================
# 7. 노드 — 비차단 / 정직 skip / 회귀
# =============================================================================
class TestNode:
    def _state(self, **over) -> dict:
        base = {"platform_intent": "web", "user_request": "할 일 앱", "deployability_result": None}
        base.update(over)
        return base

    def test_no_exec_result_skips(self) -> None:
        from src.workflows.iterative_loop import _node_documentation_lead

        out = _node_documentation_lead(self._state(chain_result=None))
        res = out["documentation_result"]
        assert isinstance(res, DocumentationResult) and res.status == "skipped"

    def test_failed_build_skips(self) -> None:
        from src.workflows.iterative_loop import _node_documentation_lead

        chain = SimpleNamespace(executor_result=SimpleNamespace(success=False, exe_path=None), saved_code_files=[], saved_dir=None)
        out = _node_documentation_lead(self._state(chain_result=chain))
        assert out["documentation_result"].status == "skipped"

    def test_web_success_generates(self, tmp_path: Path) -> None:
        from src.workflows.iterative_loop import _node_documentation_lead

        _make_web(tmp_path, {"start": "node server.js"})
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        exec_res = SimpleNamespace(success=True, exe_path=str(dist / "index.html"))
        chain = SimpleNamespace(executor_result=exec_res, saved_code_files=[], saved_dir=tmp_path)
        out = _node_documentation_lead(self._state(chain_result=chain))
        res = out["documentation_result"]
        assert res.success and res.run_command == "npm start"
        assert (tmp_path / README_NAME).is_file()

    def test_node_returns_only_documentation_key(self, tmp_path: Path) -> None:
        """비차단 보장 — 노드는 documentation_result 외 verdict/decision 키를 반환하지 않음."""
        from src.workflows.iterative_loop import _node_documentation_lead

        out = _node_documentation_lead(self._state(chain_result=None))
        assert set(out.keys()) == {"documentation_result"}

    def test_node_never_raises(self) -> None:
        """예외 silent — 어떤 망가진 state 도 노드를 깨뜨리지 않음(비차단)."""
        from src.workflows.iterative_loop import _node_documentation_lead

        bad = SimpleNamespace(executor_result=SimpleNamespace(success=True, exe_path=12345), saved_code_files=None, saved_dir=None)
        out = _node_documentation_lead(self._state(chain_result=bad))
        assert "documentation_result" in out  # 예외 대신 skip 결과


# =============================================================================
# 8. 배선 — 그래프 / telemetry / 에이전트 / GUI 불변
# =============================================================================
class TestWiring:
    def test_graph_has_documentation_node_on_complete_path(self) -> None:
        from src.workflows.iterative_loop import build_iterative_loop_graph

        graph = build_iterative_loop_graph().get_graph()
        nodes = set(graph.nodes.keys())
        assert "documentation_lead" in nodes
        edges = {(e.source, e.target) for e in graph.edges}
        assert ("curate_knowledge", "documentation_lead") in edges
        assert ("documentation_lead", "finalize") in edges
        # BLOCKED 경로는 불변(문서 미배치).
        assert ("curate_knowledge_blocked", "escalate") in edges

    def test_telemetry_department_is_learning(self) -> None:
        from src.monitoring.telemetry import LEARNING, department_for_node

        assert department_for_node("documentation_lead") == LEARNING

    def test_agent_factory_returns_agent(self) -> None:
        agent = create_documentation_lead_agent()
        assert getattr(agent, "role", "")
        # 정확성 신념이 backstory 에 명시(환각 금지 계약).
        from src.agents.knowledge import DOCUMENTATION_LEAD_BACKSTORY

        assert "실재" in DOCUMENTATION_LEAD_BACKSTORY

    def test_loop_outcome_has_documentation_result_field(self) -> None:
        """적대 리뷰 P27 — 형제 종단 산출(retrospective/curated)처럼 LoopOutcome 에 surface."""
        import src.workflows.iterative_loop as IL

        fields_set = {f.name for f in IL.LoopOutcome.__dataclass_fields__.values()}
        assert "documentation_result" in fields_set

    def test_doc_code_dir_resolution(self, tmp_path: Path) -> None:
        """_doc_code_dir — web(dist 상위)/desktop(.exe 폴더)/none(코드 위치)/망가진 입력(None)."""
        from src.workflows.iterative_loop import _doc_code_dir

        # web: code/dist/index.html → code
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("x", encoding="utf-8")
        web_exec = SimpleNamespace(success=True, exe_path=str(dist / "index.html"))
        assert _doc_code_dir(web_exec, "web", None) == tmp_path

        # desktop: code/App.exe → code (exe 가 있는 폴더)
        (tmp_path / "App.exe").write_bytes(b"MZ")
        desk_exec = SimpleNamespace(success=True, exe_path=str(tmp_path / "App.exe"))
        assert _doc_code_dir(desk_exec, "desktop", None) == tmp_path

        # none: exe 없음, saved_code_files 위치
        py = tmp_path / "main.py"
        py.write_text("x", encoding="utf-8")
        chain = SimpleNamespace(saved_code_files=[str(py)], saved_dir=tmp_path)
        none_exec = SimpleNamespace(success=True, exe_path=None)
        assert _doc_code_dir(none_exec, "none", chain) == tmp_path

        # 망가진 입력: exe_path 정수 + saved_* 없음 → None (예외 없이)
        bad_exec = SimpleNamespace(success=True, exe_path=12345)
        bad_chain = SimpleNamespace(saved_code_files=None, saved_dir=None)
        assert _doc_code_dir(bad_exec, "web", bad_chain) is None


def test_module_exports() -> None:
    import src.agents.knowledge as k

    for sym in ("generate_documentation", "DocumentationResult", "create_documentation_lead_agent"):
        assert hasattr(k, sym)

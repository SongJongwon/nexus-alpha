# Phase 2 우선순위 1 완료 보고서 — pytest 하네스 정식화

- **완료일**: 2026-04-17
- **상태**: ✅ 전 목표 달성
- **범위**: 네트워크 없이 `pytest` 한 명령으로 5개 smoke test를 통과시키는 하네스 구축. GitHub Actions CI 구성은 다음 작업으로 분리.
- **브랜치**: `phase2/pytest-harness`

---

## 1. 달성 내용 요약

| 축 | 목표 | 결과 |
|---|---|---|
| pytest 설정 | `pyproject.toml` 한 곳에서 실행 규약 정리 | `[tool.pytest.ini_options]` + `[tool.ruff]` 신규 작성 |
| 테스트 의존성 | `pytest` / `pytest-mock` / `pytest-socket` 도입 | `requirements.txt`에 추가, 버전 고정 근거 주석 |
| 공통 안전망 | 네트워크 없이 모든 테스트 통과 | `src/tests/conftest.py` — FakeProvider + LangFuse no-op + sys.path 주입 |
| 기존 smoke test | 5개 파일 pytest 호환 전환 + 직접 실행 경로 보존 | 각 파일에 `test_*` 함수 추가, `if __name__ == "__main__"` 그대로 유지 |
| 실행 검증 | `.venv/Scripts/pytest.exe` 단일 명령 통과 | **6 passed in 7.72s** (네트워크 호출 0건) |

### 완료 기준 체크

- [x] `.venv/Scripts/pytest.exe` 한 명령으로 5개 smoke 파일 전부 통과 (실제로는 **6 test case** — 어댑터 테스트 2개 + 나머지 4개).
- [x] 네트워크 없이 통과 — `get_llm_provider()`를 FakeProvider 반환으로 monkeypatch, LangFuse 로깅 메서드 전부 no-op.
- [x] 기존 `python src/tests/test_*.py` 직접 실행 경로 보존 — autouse fixture는 pytest 세션에서만 동작, 직접 실행 시에는 기존처럼 실제 LLM/LangFuse 경로 사용.
- [x] `docs/context/next_session_context.md` 최신 상태로 갱신.

---

## 2. 핵심 설계 결정

### 2-1. FakeProvider 응답 포맷 — CrewAI ReAct 파서와 1:1 정합
CrewAI 1.14.1 `crewai/agents/parser.py`의 `parse()`는 입력 텍스트에 문자열 `"Final Answer:"` 가 포함되어 있으면 해당 위치 이후를 **Agent의 최종 출력**으로 취하고 `AgentFinish`를 반환한다(`FINAL_ANSWER_ACTION` 상수).

FakeProvider의 기본 응답은 이 계약에 맞춰 다음 형태로 고정:

```
Thought: 테스트용 요청을 확인하고 최종 답변을 준비합니다.
Final Answer: 이것은 FakeProvider가 반환한 고정 응답입니다.
```

이 포맷 덕분에 `Crew.kickoff()` 가 단 **1회 LLM 호출**로 AgentFinish 경로에 도달한다 — 실제 LLM처럼 여러 차례 Thought/Action/Observation 사이클을 돌지 않는다.

### 2-2. 에이전트·워크플로우 코드는 수정 금지 (최소 침습)
`src.llm.crewai_adapter`가 모듈 탑레벨에서 `from .factory import get_llm_provider`로 심볼을 바인딩하고, `NexusAlphaLLM.__init__`이 이를 호출한다. 따라서 **두 네임스페이스 모두** monkeypatch 해야 FakeProvider 주입이 성공한다:

```python
monkeypatch.setattr(factory_module, "get_llm_provider", lambda: provider)
monkeypatch.setattr(adapter_module, "get_llm_provider", lambda: provider)
```

이 방식으로 에이전트 팩토리(`create_cto_agent` 등)나 워크플로우(`run_analyze_and_implement`) 코드에 손대지 않고도 테스트 경로만 FakeProvider로 분기된다.

### 2-3. `outputs/` 격리는 `tmp_path` 경유
워크플로우 E2E 테스트에서 `run_analyze_and_implement(outputs_dir=tmp_path, ...)`로 산출물을 임시 디렉터리로 돌려, 저장소에 `outputs/workflow_*` 디렉터리가 누적되지 않도록 한다. 기존 `if __name__ == "__main__"` 경로는 기본 `outputs/` 유지.

### 2-4. CrewAI 버전 고정
테스트 하네스가 CrewAI 내부의 `"Final Answer:"` 파서 규약에 의존하므로, `requirements.txt`에서 `crewai==1.14.1` / `crewai-tools==1.14.1`로 고정하고, 업그레이드 시 테스트 재검증이 필요하다는 주석을 남겼다.

---

## 3. 알려진 제약사항

### 3-1. pytest-socket은 Windows에서 autouse 불가 — Linux CI에서만 opt-in
초기 설계는 `pytest-socket`의 `disable_socket()`을 autouse fixture로 적용해 실수로 남은 네트워크 호출을 즉시 실패시키려 했다. 실행 결과, Windows의 `asyncio.ProactorEventLoop`가 루프 초기화 시 **내부적으로 `socket.socketpair()`**를 호출해 self-pipe를 만드는데, pytest-socket이 소켓 객체 생성 자체를 차단하는 탓에 `NexusAlphaLLM.call()` → `anyio.run()` 경로가 전부 `SocketBlockedError`로 실패했다.

**원인 호출 스택**:
```
NexusAlphaLLM.call()
  → anyio.run(self._provider.generate, ...)
    → asyncio.new_event_loop()
      → ProactorEventLoop.__init__
        → _make_self_pipe()
          → socket.socketpair()   ← pytest-socket이 차단
```

실제 외부 네트워크 호출이 아닌 **로컬 파이프 생성까지 막혀 테스트 인프라 자체가 작동 불가**한 상황. pytest-socket은 `allow_unix_socket`만 지원해서 Windows의 AF_INET socketpair를 세밀하게 예외 처리할 수도 없다.

**결정(2026-04-17)**:
1. `conftest.py`에서 pytest-socket autouse fixture를 **제거**.
2. `requirements.txt`에 `pytest-socket>=0.7.0`은 **남겨두되** 주석으로 "Windows autouse 비활성, Linux CI에서만 사용" 명시.
3. `pyproject.toml`의 `addopts`에 `--disable-socket` 포함하지 않음(Windows 기본 설정).
4. 네트워크 차단은 FakeProvider monkeypatch가 주력 안전망 — `get_llm_provider()`가 FakeProvider를 반환하도록 두 네임스페이스를 patch하므로 실제 HTTP/gRPC 경로가 원천 차단됨.
5. **Phase 2-B 재도입**: Linux 기반 GitHub Actions CI에서 `pytest --disable-socket` 플래그로 opt-in 방식으로 재도입.

### 3-2. CrewAI DeprecationWarning 잔존
`allow_code_execution` / `multimodal` 관련 경고가 42건 출력된다. 이는 CrewAI 1.14.1 내부 코드의 경고이며 테스트 정상 통과를 막지 않는다. 마이너 업그레이드 시 자연 해소될 가능성이 있어 별도 suppress는 추가하지 않았다.

### 3-3. 단일 테스트 수행 시간 분포
| 테스트 | 시간(대략) | 비고 |
|---|---|---|
| `test_crewai_adapter.py::test_adapter_uses_backend_provider_from_factory` | <1s | Pydantic 초기화 만 |
| `test_crewai_adapter.py::test_adapter_call_returns_fake_response` | ~1s | anyio.run 루프 1회 |
| `test_cto_agent.py` / `test_data_analyst_agent.py` / `test_python_engineer_agent.py` | 각 1~2s | Crew kickoff — 1회 LLM 호출로 AgentFinish 수렴 |
| `test_workflow_analyze_and_implement.py` | 3~4s | 3개 에이전트 순차 — 각 1회씩 호출 |
| **합계** | **~8s** | 목표 대비 충분히 빠름 |

---

## 4. 새로 추가/수정된 파일

```
pyproject.toml                          # NEW — pytest + ruff 설정
requirements.txt                        # UPD — pytest-*, crewai 버전 고정
src/tests/conftest.py                   # NEW — FakeProvider + autouse fixtures
src/tests/test_crewai_adapter.py        # UPD — pytest 함수 2개 추가
src/tests/test_cto_agent.py             # UPD — pytest 함수 1개 추가
src/tests/test_data_analyst_agent.py    # UPD — pytest 함수 1개 추가
src/tests/test_python_engineer_agent.py # UPD — pytest 함수 1개 추가
src/tests/test_workflow_analyze_and_implement.py # UPD — pytest 함수 1개 추가 (tmp_path)
docs/progress/phase2_priority1_complete.md # NEW — 본 보고서
docs/context/next_session_context.md    # UPD — Phase 2 우선순위 1 완료 반영
```

### pyproject.toml 핵심 설정

```toml
[tool.pytest.ini_options]
testpaths = ["src/tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = ["-v", "--strict-markers"]
pythonpath = ["."]
markers = [
    "integration: 실제 LLM/네트워크가 필요한 통합 테스트. 기본 실행에서 제외.",
]

[tool.ruff]
line-length = 100
target-version = "py313"
```

### conftest.py 3개 autouse fixture

1. `_patch_llm_factory` — `src.llm.factory.get_llm_provider` 및 `src.llm.crewai_adapter.get_llm_provider` 두 심볼을 FakeProvider 반환 람다로 치환.
2. `_silence_langfuse` — `LangFuseClient.log_trace` / `log_generation` / `end_trace` / `flush`를 no-op으로 치환.
3. (제거됨) ~~`_block_network`~~ — Windows ProactorEventLoop 호환성 문제로 제거. 3-1 참조.

### FakeProvider 핵심 계약

- `BaseLLMProvider` 상속, `_generate_impl` async 메서드가 네트워크 없이 고정 문자열 반환.
- 기본 응답은 `Thought: ...\nFinal Answer: ...` 포맷 — CrewAI ReAct 파서가 단일 호출로 AgentFinish에 수렴.
- 테스트에서 커스텀 응답이 필요하면 `fake_provider_factory(response="...")` 팩토리 fixture 사용.

---

## 5. 실행 결과

```
$ .venv/Scripts/pytest.exe
============================= test session starts =============================
platform win32 -- Python 3.13.13, pytest-9.0.3, pluggy-1.6.0
rootdir: c:\projects\nexus-alpha
configfile: pyproject.toml
testpaths: src/tests
plugins: anyio-4.13.0, langsmith-0.7.32, mock-3.15.1, socket-0.7.0
collected 6 items

src/tests/test_crewai_adapter.py::test_adapter_uses_backend_provider_from_factory PASSED
src/tests/test_crewai_adapter.py::test_adapter_call_returns_fake_response PASSED
src/tests/test_cto_agent.py::test_cto_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_data_analyst_agent.py::test_data_analyst_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_python_engineer_agent.py::test_python_engineer_agent_runs_through_crew_with_fake_provider PASSED
src/tests/test_workflow_analyze_and_implement.py::test_run_analyze_and_implement_produces_three_stage_artifacts PASSED

======================= 6 passed, 42 warnings in 7.72s ========================
```

---

## 6. 다음 작업 — Phase 2 우선순위 2 (QA 에이전트)

바로 이어질 작업은 원래 Phase 2 계획의 **2번 항목: QA 에이전트(`src/agents/qa/code_reviewer.py`)** 이다. 핵심은:

1. Engineer 산출 코드에 대해 **타입 힌트 / docstring / pytest 실행 여부**를 정적 점검하는 에이전트 추가.
2. `analyze_and_implement` 체인 끝에 QA 단계를 삽입하여 **4-agent 워크플로우**로 확장.
3. 본 pytest 하네스 위에서 QA 에이전트의 smoke test도 동일 패턴(FakeProvider autouse)으로 작성.

**Linux CI(GitHub Actions) 구성은 별도 작업**(Phase 2-B)으로 분리되어 있으며, 이때 `pytest --disable-socket` opt-in 및 `pytest -m integration` 러너를 함께 셋업한다.

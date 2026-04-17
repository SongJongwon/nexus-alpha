# LLM Provider 시스템

Nexus Alpha의 모든 에이전트/워크플로우는 Claude를 직접 호출하지 않고,
이 패키지가 제공하는 **`BaseLLMProvider` 인터페이스**를 통해 LLM에 접근합니다.
덕분에 `.env`의 환경변수 한 줄만 바꾸면 인증·과금 방식이 전환됩니다.

## 구조

```
src/llm/
├── __init__.py              # 외부 노출 API (get_llm_provider, BaseLLMProvider, NexusAlphaLLM)
├── base_provider.py         # 추상 클래스 — generate / stream / name (Template Method)
├── agent_sdk_provider.py    # MAX 구독 Provider (claude-agent-sdk 사용)
├── api_key_provider.py      # API Key Provider (langchain-anthropic 사용)
├── factory.py               # LLM_PROVIDER 환경변수 → Provider 인스턴스
└── crewai_adapter.py        # CrewAI BaseLLM ↔ BaseLLMProvider 어댑터 (NexusAlphaLLM)
```

## 기본 사용법

```python
import anyio
from src.llm import get_llm_provider

async def main() -> None:
    provider = get_llm_provider()
    print(f"Using: {provider.name}")

    answer = await provider.generate(
        prompt="한국어로 한 줄 인사해줘",
        system="당신은 친절한 한국어 비서입니다.",
    )
    print(answer)

anyio.run(main)
```

스트리밍이 필요하면 `provider.stream(...)`을 `async for`로 순회합니다.
(실제 토큰 스트리밍 지원은 Provider 구현에 따라 다릅니다.)

## Provider 전환

`.env` 파일에서 `LLM_PROVIDER` 값을 바꾸면 됩니다.

| 값 | 동작 | 필요한 것 |
|---|---|---|
| `agent_sdk` (기본) | Claude Code의 MAX 구독을 경유해 `claude` CLI를 호출 (`claude-agent-sdk`). | Claude Code가 설치·로그인되어 있어야 함 |
| `api_key`          | Anthropic Messages API를 직접 호출 (`langchain-anthropic`).            | `.env`의 `ANTHROPIC_API_KEY` 필수 |

### 예: API Key 모드로 전환

```env
# .env
LLM_PROVIDER=api_key
ANTHROPIC_API_KEY=sk-ant-xxx
```

### 예: MAX 구독 모드로 복귀

```env
# .env
LLM_PROVIDER=agent_sdk
# ANTHROPIC_API_KEY=...  # 있어도 사용되지 않음
```

## CrewAI 어댑터 (NexusAlphaLLM)

CrewAI 1.x는 LLM 파라미터로 문자열 또는 `crewai.llms.base_llm.BaseLLM` 서브클래스를 요구합니다.
`NexusAlphaLLM`은 `BaseLLM`을 상속하면서 내부에서 `BaseLLMProvider`를 위임 호출하는 얇은 어댑터로,
기존 Provider 체계(MAX ↔ API Key 전환 + LangFuse 자동 기록)를 CrewAI 세계에 그대로 넘겨줍니다.

### CrewAI Agent에 연결

```python
from crewai import Agent, Crew, Task
from src.llm import NexusAlphaLLM

llm = NexusAlphaLLM()  # factory.get_llm_provider() 자동 호출

analyst = Agent(
    role="데이터 분석가",
    goal="매출 트렌드를 요약한다",
    backstory="...",
    llm=llm,
    allow_delegation=False,
)

task = Task(description="최근 분기 매출 요약", expected_output="3문장", agent=analyst)
crew = Crew(agents=[analyst], tasks=[task])
result = crew.kickoff()
```

### 어댑터가 하는 일

1. CrewAI의 메시지 포맷(`list[{"role": "...", "content": "..."}]` 또는 `str`)을
   `(prompt, system)` 튜플로 변환.
2. 동기 `call()`에서 비동기 `BaseLLMProvider.generate()`를 안전하게 실행
   (이미 실행 중인 event loop가 있으면 별도 스레드로 회피).
3. `acall()`을 통해 async 컨텍스트에서도 직접 호출 가능.
4. `BaseLLMProvider.generate()`가 포함하는 LangFuse `log_generation` 호출을
   그대로 상속.

### 현재 지원 범위

- ✅ 텍스트 프롬프트 ↔ 텍스트 응답
- ✅ MAX ↔ API Key 전환 (`.env`)
- ✅ LangFuse 자동 기록
- ⬜ 툴 콜/function calling (tools / available_functions)
- ⬜ 구조화 출력 (response_model)
- ⬜ 콜백 (callbacks)

지원하지 않는 인자는 받아 두고 조용히 무시합니다. 이후 Phase에서 점진적으로 채웁니다.

### 직접 조회가 필요할 때

```python
llm = NexusAlphaLLM()
llm.backend_provider.name     # 현재 위임 중인 Provider 이름
llm.backend_provider          # BaseLLMProvider 인스턴스 (직접 generate 호출 가능)
```

> `provider` 라는 이름은 CrewAI `BaseLLM`이 이미 `provider: str = "openai"` 필드로 쓰고
> 있어 충돌을 피하려 `backend_provider`로 노출합니다.

## 새 Provider 추가 방법

1. `src/llm/my_provider.py` 생성, `BaseLLMProvider` 상속.
2. `name` 프로퍼티와 `async def _generate_impl(...)`를 구현.
   (추가로 `_model_identifier`, `_extra_log_metadata`를 오버라이드하면 LangFuse 기록이 풍부해진다.)
3. `factory.py`의 `_SUPPORTED`에 식별자 추가 후 분기 조건 작성.
4. `.env.example`에 새 식별자 설명 추가.

**어댑터(`NexusAlphaLLM`)와 에이전트 코드는 수정할 필요가 없습니다** — 이것이 이 구조의 핵심 이점입니다.

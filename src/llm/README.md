# LLM Provider 시스템

Nexus Alpha의 모든 에이전트/워크플로우는 Claude를 직접 호출하지 않고,
이 패키지가 제공하는 **`BaseLLMProvider` 인터페이스**를 통해 LLM에 접근합니다.
덕분에 `.env`의 환경변수 한 줄만 바꾸면 인증·과금 방식이 전환됩니다.

## 구조

```
src/llm/
├── __init__.py              # 외부 노출 API (get_llm_provider, BaseLLMProvider)
├── base_provider.py         # 추상 클래스 — generate / stream / name
├── agent_sdk_provider.py    # MAX 구독 Provider (claude-agent-sdk 사용)
├── api_key_provider.py      # API Key Provider (langchain-anthropic 사용)
└── factory.py               # LLM_PROVIDER 환경변수 → Provider 인스턴스
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

## 새 Provider 추가 방법

1. `src/llm/my_provider.py` 생성, `BaseLLMProvider` 상속.
2. `name` 프로퍼티와 `async def generate(...)`를 구현.
3. `factory.py`의 `_SUPPORTED`에 식별자 추가 후 분기 조건 작성.
4. `.env.example`에 새 식별자 설명 추가.

기존 에이전트 코드는 일체 변경하지 않아도 된다는 점이 이 구조의 핵심 이점입니다.

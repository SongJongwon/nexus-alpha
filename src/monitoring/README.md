# 모니터링 (LangFuse)

Nexus Alpha의 모든 LLM 호출과 에이전트 실행은 **LangFuse**로 자동 기록됩니다.
Provider 레이어(`src/llm/*`)가 공통적으로 로깅을 호출하기 때문에,
새 Provider나 새 에이전트를 추가해도 별도 계측 코드 없이 바로 추적됩니다.

## 동작 개요

- 싱글톤 `LangFuseClient`가 프로세스 내에서 한 번만 초기화됨.
- `.env`의 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`를 읽음.
- **키가 비어 있으면 경고만 출력하고 모든 메서드가 조용히 no-op** — 메인 기능은 영향받지 않음.
- `BaseLLMProvider.generate()`가 내부적으로 `log_generation`을 호출하므로
  어떤 Provider를 써도 같은 방식으로 기록됩니다.

## 환경변수 (`.env`)

```env
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_HOST="https://cloud.langfuse.com"
```

## 사용 예시

```python
import anyio
from src.llm import get_llm_provider
from src.monitoring import get_langfuse_client


async def main() -> None:
    monitor = get_langfuse_client()
    monitor.log_trace(name="demo_task", user_id="user-001", metadata={"phase": 1})

    provider = get_llm_provider()
    # provider.generate() 안에서 자동으로 log_generation이 호출됨
    reply = await provider.generate(
        prompt="오늘의 업무를 요약해줘",
        system="당신은 사용자 비서입니다.",
    )
    print(reply)

    monitor.end_trace()
    monitor.flush()  # 프로세스 종료 직전에 반드시 호출 — 버퍼링된 이벤트 전송


anyio.run(main)
```

## 대시보드

실행 직후 다음 URL에서 trace / generation을 확인할 수 있습니다:

- **Cloud 기본**: <https://cloud.langfuse.com>
- Self-hosted 사용 중이면 `.env`의 `LANGFUSE_HOST` 값으로 대체.

## 문제 해결

- 콘솔에 `[LangFuse] 초기화 실패: ...`가 찍히면 키/HOST 값을 확인하세요.
- 이벤트가 대시보드에 보이지 않으면 프로세스 종료 전 `flush()` 호출 여부를 확인.
- 비활성화 모드(키 누락)에서도 애플리케이션은 정상 동작합니다 — 기록만 건너뜁니다.

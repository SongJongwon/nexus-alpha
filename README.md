# 🏢 Nexus Alpha

업무 자동화/RPA 전문 AI 가상 기업 시스템

## 📖 프로젝트 개요

Nexus Alpha는 사용자의 반복 업무를 분석하여 자동화 스크립트·봇·워크플로우를
생성하는 **AI 컨설팅 & 개발 기업 시스템**입니다. 여러 역할(C-Level, 분석, 기획,
엔지니어링, QA, 지식, 운영)의 에이전트가 협업하여 업무 요구를 자동화 산출물로
변환합니다.

## 🛠️ 기술 스택

- **언어**: Python 3.13
- **오케스트레이션**: CrewAI + LangGraph
- **LLM 연동**: Claude Agent SDK (MAX 구독) / Anthropic API Key
- **데이터 처리**: Pandas, OpenPyXL
- **검증**: Pydantic
- **유틸**: Rich (콘솔 UI), PyYAML, python-dotenv

## ✨ 주요 기능

- 🔄 **LLM Provider 추상화** — MAX 구독 ↔ API Key 자유 전환 (`.env` 한 줄 변경)
- 🏗️ **Factory 패턴** 기반 확장성 — 새 Provider 추가 시 기존 에이전트 코드 무수정
- 📁 체계적인 프로젝트 구조 — 역할별 에이전트 디렉터리 분리
- 🌐 Cross-platform 지원 (Windows / macOS / Linux)

## 🚀 설치 및 실행

### 사전 준비

- Python 3.13 이상
- (선택) Claude Code 로그인 (MAX 구독 모드 사용 시)
- (선택) Anthropic API Key (`sk-ant-...`) — API Key 모드 사용 시

### 1) 저장소 클론

```bash
git clone https://github.com/SongJongwon/nexus-alpha.git
cd nexus-alpha
```

### 2) 가상환경 생성 및 활성화

Windows (bash):
```bash
py -3.13 -m venv .venv
source .venv/Scripts/activate
```

Windows (PowerShell):
```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:
```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### 3) 의존성 설치

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4) 환경변수 설정

`.env` 파일(루트)을 편집하세요.

```env
# MAX 구독 모드 (기본, 무료)
LLM_PROVIDER=agent_sdk

# API Key 모드로 전환하려면 아래 두 줄을 활성화
# LLM_PROVIDER=api_key
# ANTHROPIC_API_KEY=sk-ant-...
```

### 5) Hello Agent 테스트

```bash
.venv/Scripts/python.exe src/tests/hello_agent.py
# 또는 (macOS/Linux)
python src/tests/hello_agent.py
```

정상 동작 시 Provider 이름과 한국어 인사 응답이 출력됩니다.

## 📂 프로젝트 구조

```
nexus-alpha/
├── README.md                  # 본 문서
├── requirements.txt           # Python 의존성
├── .env                       # 환경변수 (Git 추적 제외)
├── .gitignore
├── src/
│   ├── agents/                # 역할별 에이전트 모듈
│   │   ├── c_level/           #   C-Level (경영 의사결정)
│   │   ├── analysis/          #   데이터 분석
│   │   ├── planning/          #   기획
│   │   ├── engineering/       #   구현/개발
│   │   ├── qa/                #   품질 보증
│   │   ├── knowledge/         #   지식 관리
│   │   └── operations/        #   운영
│   ├── llm/                   # LLM Provider 추상화
│   │   ├── base_provider.py   #   BaseLLMProvider (ABC)
│   │   ├── agent_sdk_provider.py  # Claude Code MAX 경로
│   │   ├── api_key_provider.py    # Anthropic API Key 경로
│   │   ├── factory.py         #   LLM_PROVIDER → Provider 인스턴스
│   │   └── README.md
│   ├── workflows/             # 에이전트 간 워크플로우 정의
│   ├── config/                # 공통 설정 파일
│   └── tests/                 # 통합/단위 테스트
│       └── hello_agent.py     #   Provider 시스템 smoke test
├── outputs/                   # 실행 산출물 (Git 추적 제외)
└── logs/                      # 실행 로그 (Git 추적 제외)
```

## 📊 진행 현황

- ✅ **Phase 0**: 기반 구축 완료 (2026-04-17)
- ⬜ Phase 1: MVP 3개 부서 (진행 예정)
- ⬜ Phase 2: 전체 조직 확장
- ⬜ Phase 3: 실행 엔진 통합
- ⬜ Phase 4: 하이브리드 UI
- ⬜ Phase 5: 파일럿 프로젝트

## 📝 라이선스

Private Project — All Rights Reserved

# LangGraph Chat Agent

LangGraph 기반 채팅 에이전트 프로젝트

## 기능

- **기본 대화**: OpenRouter를 통한 LLM 대화
- **도구 사용**: Tool calling 지원 (계산기 등)
- **RAG**: 문서 기반 질의응답
- **메모리**: 인메모리 대화 기록 유지

## 아키텍처

```
User Input → router → agent (LLM) ←→ tools
                ↓           ↓
               rag ─────────┘
                      ↓
                   Response
```

### StateGraph 노드

| 노드 | 역할 |
|------|------|
| `router` | 입력 분석 후 다음 노드 결정 |
| `agent` | LLM 호출, 도구 바인딩 |
| `tools` | 도구 실행 (ToolNode) |
| `rag` | 문서 검색 후 컨텍스트 제공 |

## 프로젝트 구조

```
src/
├── config/settings.py      # 설정 관리
├── llm/openrouter.py       # OpenRouter LLM 연동
├── state/agent_state.py    # AgentState 정의
├── nodes/
│   ├── router.py           # 라우터 노드
│   ├── agent.py            # LLM 호출 노드
│   ├── tool_executor.py    # 도구 실행 노드
│   └── rag.py              # RAG 검색 노드
├── tools/
│   ├── calculator.py       # 계산기 도구
│   └── registry.py         # 도구 레지스트리
├── rag/
│   ├── vector_store.py     # 인메모리 벡터 스토어
│   └── retriever.py        # 리트리버
├── graph/builder.py        # StateGraph 빌더
└── agent.py                # ChatAgent 클래스
main.py                     # CLI 엔트리포인트
```

## 설치 및 실행

```bash
# 가상환경 활성화
source venv/bin/activate

# 환경변수 설정
cp .env.example .env
# .env 파일에 OPENROUTER_API_KEY 설정

# 실행
python main.py
```

## 환경변수

| 변수 | 설명 |
|------|------|
| `OPENROUTER_API_KEY` | OpenRouter API 키 |
| `DEFAULT_MODEL` | 기본 모델 (예: `anthropic/claude-3.5-sonnet`) |
| `DEFAULT_TEMPERATURE` | 샘플링 온도 (기본: 0.7) |

## 핵심 코드 패턴

### OpenRouter 연동

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="anthropic/claude-3.5-sonnet",
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)
```

### AgentState

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    context: Optional[str]
    next_action: Optional[str]
```

### 그래프 빌드

```python
workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", ToolNode(tools))
workflow.add_conditional_edges("agent", route_by_action)
graph = workflow.compile(checkpointer=InMemorySaver())
```

## 사용 예시

```python
from src.agent import ChatAgent

agent = ChatAgent(thread_id="session-1")

# 기본 대화
response = agent.chat("안녕하세요")

# 도구 사용
response = agent.chat("123 * 456은?")

# 스트리밍
for event in agent.stream("설명해줘"):
    print(event)
```

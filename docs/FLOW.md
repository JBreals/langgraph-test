# 채팅 에이전트 플로우

## 전체 그래프 구조

```
           ┌───────────┐
           │  __start__│
           └─────┬─────┘
                 │
                 ▼
           ┌───────────┐
           │  router   │ ← LLM: rag vs agent 판단
           └─────┬─────┘
                 │
        ┌────────┴────────┐
        │                 │
        ▼                 ▼
   ┌─────────┐      ┌─────────┐
   │   rag   │      │ memory  │ ← 메시지 수 체크, 필요시 요약
   │ (검색)  │      └────┬────┘
   └────┬────┘           │
        │                │
        ▼                │
   ┌─────────┐           │
   │ memory  │           │
   └────┬────┘           │
        │                │
        └───────┬────────┘
                │
                ▼
           ┌─────────┐
           │  agent  │ ← LLM: 대화 + 도구 결정
           └────┬────┘
                │
           ┌────┴────┐
           │         │
           ▼         ▼
      ┌─────────┐ ┌─────────┐
      │ __end__ │ │  tools  │
      └─────────┘ └────┬────┘
                       │
                       ▼
                  ┌─────────┐
                  │  agent  │
                  └─────────┘
```

## 노드별 역할

| 노드 | LLM 사용 | 역할 |
|------|----------|------|
| router | O | 의도 분류 (rag vs agent) |
| rag | X | 벡터스토어 검색, context 저장 |
| memory | △ | 메시지 수 초과 시 LLM으로 요약 |
| agent | O | 대화 생성 + 도구 호출 결정 |
| tools | X | 도구 함수 실행 |

---

## 하이브리드 메모리 시스템

### 구조

```
┌─────────────────────────────────────────────────────────────┐
│                      AgentState                             │
├─────────────────────────────────────────────────────────────┤
│  messages: [최근 메시지들]     ← 최대 MAX_MESSAGES개 유지    │
│  summary: "이전 대화 요약"     ← 오래된 대화는 여기에 누적    │
│  context: "RAG 검색 결과"                                   │
└─────────────────────────────────────────────────────────────┘
```

### 설정값 (src/nodes/memory.py)

```python
MAX_MESSAGES = 10   # 최대 메시지 수 (초과 시 요약)
KEEP_RECENT = 5     # 요약 후 유지할 최근 메시지 수
```

### 동작 흐름

```
[초기] messages: 0개, summary: ""

  ↓ 대화 진행...

[상태1] messages: 10개, summary: ""
  ↓ (MAX_MESSAGES 도달, 요약 트리거)

[상태2] messages: 5개, summary: "요약1"
        ─────────────────
        오래된 5개 → 요약으로 변환
        최근 5개 → 유지

  ↓ 대화 진행...

[상태3] messages: 10개, summary: "요약1"
  ↓ (다시 MAX_MESSAGES 도달)

[상태4] messages: 5개, summary: "요약1---BREAK---요약2"
        ─────────────────
        오래된 5개 → 새 요약 생성
        슬라이딩 윈도우에 추가
        최근 5개 → 유지

  ↓ 계속 반복...
```

### 슬라이딩 윈도우 요약 관리

**설정값** (`src/memory/summarizer.py`):
```python
MAX_SUMMARIES = 3           # 최대 유지할 요약 개수
SUMMARY_SEPARATOR = "\n---SUMMARY_BREAK---\n"  # 요약 구분자
```

**요약 저장 구조**:
```
"요약1" ---SUMMARY_BREAK--- "요약2" ---SUMMARY_BREAK--- "요약3"
  ↑                            ↑                          ↑
가장 오래됨                                            가장 최신
```

**슬라이딩 동작**:
```
[1회차 요약] summary = "요약1"
[2회차 요약] summary = "요약1---BREAK---요약2"
[3회차 요약] summary = "요약1---BREAK---요약2---BREAK---요약3"
[4회차 요약] summary = "요약2---BREAK---요약3---BREAK---요약4"
                        ↑
                    요약1 삭제 (슬라이딩)
```

**핵심 함수**:
```python
def add_summary_to_window(existing_summary: str, new_summary: str) -> str:
    # 1. 기존 요약을 리스트로 분리
    summaries = existing_summary.split(SUMMARY_SEPARATOR)

    # 2. 새 요약 추가
    summaries.append(new_summary)

    # 3. MAX_SUMMARIES 초과 시 오래된 것 삭제
    if len(summaries) > MAX_SUMMARIES:
        summaries = summaries[-MAX_SUMMARIES:]

    # 4. 다시 문자열로 결합
    return SUMMARY_SEPARATOR.join(summaries)
```

**프롬프트 포맷팅**:
```python
def format_summary_for_prompt(summary: str) -> str:
    # 구분자로 분리 후 번호 붙여서 반환
    # [대화 기록 1]
    # 요약 내용...
    #
    # [대화 기록 2]
    # 요약 내용...
```

### 프롬프트 구성

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM에 전달되는 메시지                     │
├─────────────────────────────────────────────────────────────┤
│  [SystemMessage]                                            │
│  당신은 도움이 되는 AI 어시스턴트입니다.                      │
│                                                             │
│  [이전 대화 요약]        ← state.summary (요약 누적)         │
│  사용자 이름은 철수, 프로젝트 마감일은 3월...                 │
│                                                             │
│  [참고 문서]             ← state.context (RAG 결과)          │
│  휴가 정책: 연차 15일...                                     │
├─────────────────────────────────────────────────────────────┤
│  [HumanMessage] 최근 대화 1                                  │
│  [AIMessage] 최근 대화 2                                     │
│  ...                                                        │
│  [HumanMessage] 현재 질문     ← 최근 KEEP_RECENT개만         │
└─────────────────────────────────────────────────────────────┘
```

### 토큰 절약 효과

```
[요약 없이 - 기존 방식]
대화 50개 = 약 50,000 토큰 (대화당 ~1000토큰 가정)

[하이브리드 방식]
요약 (~500토큰) + 최근 5개 (~5,000토큰) = 약 5,500 토큰

→ 약 90% 토큰 절약
```

---

## 시나리오 1: 단순 대화

**입력**: "안녕하세요"

```
User: "안녕하세요"
         │
         ▼
    ┌─────────┐
    │ router  │ ──► LLM: "일반 대화" → memory
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ memory  │ ──► 메시지 수 체크 (임계값 이하면 통과)
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM 호출
    │  (LLM)  │     tool_calls = []
    └────┬────┘     next_action = "end"
         │
         ▼
    ┌─────────┐
    │   END   │
    └─────────┘
```

**LLM 호출**: 2회 (router 1회 + agent 1회)

---

## 시나리오 2: 도구 사용 (계산기)

**입력**: "123 * 456 계산해줘"

```
User: "123 * 456 계산해줘"
         │
         ▼
    ┌─────────┐
    │ router  │ ──► LLM: "일반 질문" → memory
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ memory  │ ──► 통과
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM: "계산기 필요"
    │  (LLM)  │     tool_calls = [calculator("123 * 456")]
    └────┬────┘     next_action = "tools"
         │
         ▼
    ┌─────────┐
    │  tools  │ ──► calculator 실행 (LLM 없음)
    │ToolNode │     result = "56088"
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM: 도구 결과로 답변 생성
    │  (LLM)  │     tool_calls = []
    └────┬────┘     next_action = "end"
         │
         ▼
    ┌─────────┐
    │   END   │
    └─────────┘
```

**LLM 호출**: 3회 (router 1회 + agent 2회)

---

## 시나리오 3: RAG (문서 검색)

**입력**: "회사 휴가 정책이 뭐야?"

```
User: "회사 휴가 정책이 뭐야?"
         │
         ▼
    ┌─────────┐
    │ router  │ ──► LLM: "문서 검색 필요" → rag
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │   rag   │ ──► 벡터스토어 검색 (LLM 없음)
    │retrieve │     context = "연차: 15일, 병가: 10일..."
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ memory  │ ──► 통과
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM 호출 (summary + context 포함)
    │  (LLM)  │     시스템 프롬프트에 문서 내용 추가
    └────┬────┘     next_action = "end"
         │
         ▼
    ┌─────────┐
    │   END   │
    └─────────┘
```

**LLM 호출**: 2회 (router 1회 + agent 1회)

---

## 시나리오 4: 긴 대화 (메모리 요약)

```
[대화 10개 진행 후]

User: "아까 말한 프로젝트 마감일이 언제라고 했지?"
         │
         ▼
    ┌─────────┐
    │ router  │ ──► agent
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ memory  │ ──► 메시지 10개 = MAX_MESSAGES
    │         │     요약 트리거!
    │         │     ┌────────────────────────────┐
    │         │     │ 오래된 5개 메시지 요약      │
    │         │     │ "사용자 이름: 철수         │
    │         │     │  프로젝트 마감: 3월 15일   │
    │         │     │  예산: 1억원"              │
    │         │     └────────────────────────────┘
    └────┬────┘     summary 업데이트, 최근 5개 유지
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM 호출
    │  (LLM)  │     시스템 프롬프트:
    │         │     - [이전 대화 요약] ← 요약 내용
    │         │     - 최근 5개 메시지
    └────┬────┘
         │
         ▼
AI: "프로젝트 마감일은 3월 15일이라고 말씀하셨습니다."
```

**LLM 호출**: 3회 (router 1회 + memory 요약 1회 + agent 1회)

---

## 시나리오 5: 멀티턴 대화 (체크포인터)

```
[Turn 1]
User: "내 이름은 철수야"
AI: "안녕하세요 철수님! 반갑습니다."
      ↓
    MemorySaver에 저장 (thread_id: "abc-123")

[Turn 2 - 프로세스 재시작 후에도 기억]
User: "내 이름이 뭐라고 했지?"
      ↓
    MemorySaver에서 이전 상태 로드
      ↓
AI: "철수님이라고 하셨습니다."
```

**MemorySaver 저장 내용**:
```python
{
    "messages": [...],
    "summary": "사용자 이름은 철수...",
    "context": None,
    "next_action": None,
}
```

---

## 라우팅 로직

### router 노드 (LLM 기반)

```python
class RouteDecision(BaseModel):
    route: Literal["rag", "agent"]
    reason: str

ROUTER_PROMPT = """
- rag: 회사 문서, 정책, 규정 등 저장된 문서에서 정보를 찾아야 하는 질문
- agent: 일반 대화, 계산, 코딩, 날씨, 검색 등
"""

def router_node(state):
    llm = get_llm(temperature=0)
    structured_llm = llm.with_structured_output(RouteDecision)
    response = structured_llm.invoke([...])
    return {"next_action": response.route}
```

### memory 노드

```python
def memory_node(state):
    if count_messages(state["messages"]) > MAX_MESSAGES:
        # 오래된 메시지 요약
        old_messages = state["messages"][:-KEEP_RECENT]
        new_summary = summarize_messages(old_messages)

        # 기존 요약과 병합
        combined = f"{state['summary']}\n\n{new_summary}"

        return {
            "summary": combined,
            "messages": [RemoveMessage(id=m.id) for m in old_messages]
        }
    return {}
```

### agent 노드 후 라우팅

```python
def route_after_agent(state) -> str:
    next_action = state.get("next_action", "end")

    if next_action == "tools":
        return "tools"
    return "__end__"
```

---

## 등록된 도구

| 도구 | 설명 | API 키 필요 |
|------|------|-------------|
| calculator | 수학 계산 | X |
| get_current_datetime | 날짜/시간 조회 | X |
| get_weather | 날씨 조회 | OPENWEATHER_API_KEY |
| search_wikipedia | 위키피디아 검색 | X |
| web_search | 웹 검색 | TAVILY_API_KEY |
| python_repl | Python 실행 | X |
| read_file | 파일 읽기 | X |

---

## 벡터 스토어 옵션

| 타입 | 설명 | 임베딩 | 영속성 |
|------|------|--------|--------|
| memory | 키워드 기반 (기본) | 불필요 | X |
| faiss | FAISS 벡터 검색 | 필요 | 로컬 파일 |
| opensearch | OpenSearch 클러스터 | 필요 | 클러스터 |

```python
from src.rag import init_vector_store

# 인메모리
init_vector_store("memory")

# FAISS
init_vector_store("faiss", index_path="./faiss_index")

# OpenSearch
init_vector_store("opensearch", opensearch_url="http://localhost:9200")
```

---

## LLM 호출 횟수 요약

| 시나리오 | router | memory | agent | 총 호출 |
|----------|--------|--------|-------|---------|
| 단순 대화 | 1 | 0 | 1 | 2 |
| 도구 사용 | 1 | 0 | 2 | 3 |
| RAG | 1 | 0 | 1 | 2 |
| 긴 대화 (요약) | 1 | 1 | 1 | 3 |
| RAG + 도구 | 1 | 0 | 2 | 3 |

---

## 에러 처리 플로우

```
User: "잘못된 계산식"
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► tool_calls = [calculator("abc")]
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  tools  │ ──► 실행 오류 발생
    │ToolNode │     ToolMessage(content="Error: invalid syntax")
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► 에러 메시지 기반 응답
    └────┬────┘
         │
         ▼
AI: "죄송합니다. 계산식이 올바르지 않습니다."
```

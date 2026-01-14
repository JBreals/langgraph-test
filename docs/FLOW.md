# 채팅 에이전트 플로우

## 전체 그래프 구조

```
                    ┌──────────┐
                    │  START   │
                    └────┬─────┘
                         │
                         ▼
                    ┌──────────┐
            ┌───────│  router  │───────┐
            │       └────┬─────┘       │
            │            │             │
            ▼            ▼             ▼
       ┌────────┐   ┌────────┐   ┌────────┐
       │  rag   │   │ agent  │   │ tools  │
       └────┬───┘   └────┬───┘   └────┬───┘
            │            │             │
            └─────►──────┴──────◄──────┘
                         │
                         ▼
                    ┌──────────┐
                    │   END    │
                    └──────────┘
```

---

## 시나리오 1: 단순 대화

**입력**: "안녕하세요"

```
User: "안녕하세요"
         │
         ▼
    ┌─────────┐
    │  START  │
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ router  │ ──► next_action = "agent"
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
         │
         ▼
AI: "안녕하세요! 무엇을 도와드릴까요?"
```

**메시지 상태 변화**:
```python
# 입력
messages: [HumanMessage("안녕하세요")]

# agent 후
messages: [
    HumanMessage("안녕하세요"),
    AIMessage("안녕하세요! 무엇을 도와드릴까요?")
]
```

---

## 시나리오 2: 도구 사용 (계산기)

**입력**: "123 * 456 계산해줘"

```
User: "123 * 456 계산해줘"
         │
         ▼
    ┌─────────┐
    │  START  │
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ router  │ ──► next_action = "agent"
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM 호출
    │  (LLM)  │     tool_calls = [calculator("123 * 456")]
    └────┬────┘     next_action = "tools"
         │
         ▼
    ┌─────────┐
    │  tools  │ ──► calculator 실행
    │ToolNode │     result = "56088"
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM 호출 (도구 결과 포함)
    │  (LLM)  │     tool_calls = []
    └────┬────┘     next_action = "end"
         │
         ▼
    ┌─────────┐
    │   END   │
    └─────────┘
         │
         ▼
AI: "123 * 456 = 56,088 입니다."
```

**메시지 상태 변화**:
```python
# 입력
messages: [HumanMessage("123 * 456 계산해줘")]

# agent 1차 호출 후
messages: [
    HumanMessage("123 * 456 계산해줘"),
    AIMessage(tool_calls=[{"name": "calculator", "args": {"expression": "123 * 456"}}])
]

# tools 실행 후
messages: [
    HumanMessage("123 * 456 계산해줘"),
    AIMessage(tool_calls=[...]),
    ToolMessage(content="56088", name="calculator")
]

# agent 2차 호출 후 (최종)
messages: [
    HumanMessage("123 * 456 계산해줘"),
    AIMessage(tool_calls=[...]),
    ToolMessage(content="56088", name="calculator"),
    AIMessage("123 * 456 = 56,088 입니다.")
]
```

---

## 시나리오 3: RAG (문서 검색)

**입력**: "회사 휴가 정책이 뭐야?"

```
User: "회사 휴가 정책이 뭐야?"
         │
         ▼
    ┌─────────┐
    │  START  │
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ router  │ ──► 문서 검색 필요 감지
    └────┬────┘     next_action = "rag"
         │
         ▼
    ┌─────────┐
    │   rag   │ ──► 벡터스토어 검색
    │retrieve │     context = "연차: 15일, 병가: 10일..."
    └────┬────┘     next_action = "agent"
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► LLM 호출 (context 포함)
    │  (LLM)  │     문서 기반 답변 생성
    └────┬────┘     next_action = "end"
         │
         ▼
    ┌─────────┐
    │   END   │
    └─────────┘
         │
         ▼
AI: "회사 휴가 정책에 따르면 연차는 15일, 병가는 10일입니다..."
```

**상태 변화**:
```python
# rag 노드 후
context: "연차: 15일, 병가: 10일..."

# agent 호출 시 시스템 메시지에 context 추가
system_message = """
당신은 AI 어시스턴트입니다.

참고 문서:
연차: 15일, 병가: 10일...
"""
```

---

## 시나리오 4: 멀티턴 대화 (메모리)

```
[Turn 1]
User: "내 이름은 철수야"
AI: "안녕하세요 철수님! 반갑습니다."

[Turn 2]
User: "내 이름이 뭐라고 했지?"
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► messages에서 이전 대화 참조
    │  (LLM)  │
    └────┬────┘
         │
         ▼
AI: "철수님이라고 하셨습니다."
```

**InMemorySaver 동작**:
```python
# thread_id로 대화 분리
config = {"configurable": {"thread_id": "user-123"}}

# Turn 1 후 저장된 상태
checkpoint = {
    "messages": [
        HumanMessage("내 이름은 철수야"),
        AIMessage("안녕하세요 철수님!")
    ]
}

# Turn 2에서 이전 메시지 자동 로드
```

---

## 시나리오 5: 복합 (RAG + 도구)

**입력**: "팀 예산이 얼마야? 20% 증가하면?"

```
User: "팀 예산이 얼마야? 20% 증가하면?"
         │
         ▼
    ┌─────────┐
    │ router  │ ──► next_action = "rag"
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │   rag   │ ──► context = "2024년 팀 예산: 1억원"
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► tool_calls = [calculator("100000000 * 1.2")]
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  tools  │ ──► result = "120000000"
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │  agent  │ ──► 최종 답변 생성
    └────┬────┘
         │
         ▼
AI: "현재 팀 예산은 1억원이고, 20% 증가 시 1.2억원입니다."
```

---

## 조건부 라우팅 로직

### router 노드

```python
def router_node(state: AgentState) -> dict:
    last_message = state["messages"][-1]

    # AIMessage에 tool_calls가 있으면 → tools
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return {"next_action": "tools"}

    # RAG 필요 여부 판단
    if needs_rag(last_message):
        return {"next_action": "rag"}

    # 기본 → agent
    return {"next_action": "agent"}
```

### agent 노드 후 라우팅

```python
def route_after_agent(state: AgentState) -> str:
    last_message = state["messages"][-1]

    # tool_calls가 있으면 → tools
    if last_message.tool_calls:
        return "tools"

    # 없으면 → 종료
    return "__end__"
```

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
AI: "죄송합니다. 계산식이 올바르지 않습니다. 다시 입력해주세요."
```

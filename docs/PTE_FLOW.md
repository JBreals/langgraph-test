# Plan-then-Execute (PTE) 에이전트 플로우

## 전체 그래프 구조

```
                    ┌────────────────┐
                    │   __start__    │
                    └───────┬────────┘
                            │
                            ▼
                    ┌────────────────┐
                    │    Intent      │ ← LLM: 의도 분류, 쿼리 재작성
                    │   Classifier   │
                    └───────┬────────┘
                            │
                    ┌───────┴───────┐
                    │               │
             (needs_tool=true)  (needs_tool=false)
                    │               │
                    ▼               │
            ┌────────────────┐      │
            │    Planner     │      │
            │   (컴파일러)    │      │
            └───────┬────────┘      │
                    │               │
            ┌───────┴───────┐       │
            │               │       │
       (JSON 성공)      (JSON 실패) │
            │               │       │
            ▼               ▼       │
     ┌──────────────┐ ┌──────────┐  │
     │  has_plan?   │ │  Error   │  │
     └──────┬───────┘ │ Handler  │  │
            │         └────┬─────┘  │
    ┌───────┴───────┐      │        │
    │               │      ▼        │
 (plan 있음)    (plan 없음) __end__  │
    │               │               │
    ▼               └───────┬───────┘
┌────────────┐              │
│  Executor  │◄─────┐       │
│  (런타임)   │      │       │
└─────┬──────┘      │       │
      │             │       │
      ▼             │       │
┌─────────────┐     │       │
│check_result │     │       │
└─────┬───────┘     │       │
      │             │       │
┌─────┴─────┐       │       │
│           │       │       │
(성공)    (실패)    │       │
│           │       │       │
│           ▼       │       │
│    ┌───────────┐  │       │
│    │Re-planner │──┘       │
│    └─────┬─────┘          │
│          │                │
│   ┌──────┴──────┐         │
│   │             │         │
│(재계획)    (한계 초과)     │
│   │             │         │
│   ▼             ▼         │
│ Executor  ┌──────────┐    │
│           │  Error   │    │
│           │ Handler  │    │
│           └────┬─────┘    │
│                │          │
│                ▼          │
│             __end__       │
│                           │
└───────┬───────────────────┘
        │
        ▼
 has_more_steps?
        │
┌───────┴───────┐
│               │
(더 있음)     (완료)
│               │
▼               ▼
Executor   ┌─────────────┐
           │   Final     │
           │   Answer    │
           └──────┬──────┘
                  │
                  ▼
               __end__
```

---

## 노드별 역할

| 노드 | LLM 사용 | 역할 | 입력 | 출력 |
|------|----------|------|------|------|
| Intent Classifier | O (1회) | 의도 분류, 쿼리 재작성, 도구 필요 여부 판단 | `input`, `messages` | `intent`, `rewritten_query`, `needs_tool` |
| Planner | O (1회) | 사용자 요청 → 실행 계획 변환 | `input`, `tool_manifest` | `plan` |
| Executor | X | plan의 step 실행 | `plan[0]` | `past_steps` |
| Re-planner | O (실패 시) | 실패 분석 및 계획 수정 | `plan`, `past_steps` | `plan` (수정) |
| Final Answer | O (1회) | 실행 결과 정리 또는 일반 대화 처리 | `past_steps`, `input` | `result` |
| Error Handler | X | Fail-closed 처리 | `error` | `result` |

---

## State 스키마

```python
class PTEState(TypedDict):
    # 입력
    input: str                      # 사용자 요청 원문
    messages: list[dict]            # 대화 히스토리 [{"role": "user"|"assistant", "content": "..."}]
    current_datetime: str           # 현재 시각 (KST)

    # Intent Classifier 출력
    intent: str                     # 의도 유형: new_question | follow_up | clarification | chitchat
    rewritten_query: str            # 명확하게 재작성된 쿼리
    needs_tool: bool                # 도구 필요 여부

    # 도구 정보
    tool_manifest: str              # 사용 가능한 도구 설명
    available_tools: list[str]      # 도구 이름 목록

    # 계획
    plan: list[dict]                # 실행 대기 중인 step 목록
    # 예: [{"step_id": 1, "tool": "web_search", "input": "LangGraph"}]

    # 실행 로그
    past_steps: list[dict]          # 실행 완료된 step과 결과
    # 예: [{"step": {...}, "status": "success", "output": "..."}]

    # 제어
    replan_count: int               # 재계획 횟수 (무한 루프 방지)
    error: str | None               # 에러 메시지 (있으면 즉시 중단)

    # 출력
    result: str | None              # 사용자에게 반환할 최종 결과
```

---

## Intent 유형

| Intent | 설명 | 예시 | needs_tool |
|--------|------|------|------------|
| `new_question` | 새로운 주제에 대한 질문 | "서울 맛집 추천해줘" | true |
| `follow_up` | 이전 대화의 후속 질문 | "더 있어?", "다른 건?" | true |
| `clarification` | 이전 답변에 대한 명확화 요청 | "무슨 말이야?", "예시 들어줘" | 상황에 따라 |
| `chitchat` | 인사, 감사, 잡담 | "고마워", "안녕", "ㅋㅋ" | false |
| (콘텐츠 처리) | 질문 없이 긴 본문만 제공 | 기사 본문, 코드 덤프 | false |

---

## 시나리오 1: 단순 질문 (도구 1개)

**입력**: "서울 날씨 알려줘"

```
User: "서울 날씨 알려줘"
         │
         ▼
┌─────────────────┐
│Intent Classifier│ ──► LLM 호출 (1회)
│                 │     intent = "new_question"
│                 │     rewritten_query = "서울 날씨"
│                 │     needs_tool = true
└────────┬────────┘
         │
         ▼
    ┌─────────┐
    │ Planner │ ──► LLM 호출 (1회)
    │         │     plan = [
    │         │       {"step_id": 1, "tool": "web_search", "input": "서울 날씨"}
    │         │     ]
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │Executor │ ──► web_search("서울 날씨") 실행
    │         │     past_steps = [{
    │         │       "step": {"step_id": 1, "tool": "web_search", ...},
    │         │       "status": "success",
    │         │       "output": "맑음, 15°C"
    │         │     }]
    └────┬────┘
         │ plan이 비었음
         ▼
    ┌─────────┐
    │  Final  │ ──► LLM 호출 (1회)
    │ Answer  │     result = "서울의 현재 날씨는 맑고 15°C입니다."
    └────┬────┘
         │
         ▼
      __end__
```

**LLM 호출**: 3회 (Intent 1회 + Planner 1회 + Final Answer 1회)

---

## 시나리오 2: 잡담 (도구 불필요)

**입력**: "고마워!"

```
User: "고마워!"
         │
         ▼
┌─────────────────┐
│Intent Classifier│ ──► LLM 호출 (1회)
│                 │     intent = "chitchat"
│                 │     needs_tool = false
└────────┬────────┘
         │ needs_tool = false
         ▼
    ┌─────────┐
    │  Final  │ ──► LLM 호출 (1회)
    │ Answer  │     GENERAL_CONVERSATION_PROMPT 사용
    │         │     result = "별말씀을요! 더 궁금한 거 있으면 말씀해주세요."
    └────┬────┘
         │
         ▼
      __end__
```

**LLM 호출**: 2회 (Intent 1회 + Final Answer 1회)
**특징**: Planner/Executor를 거치지 않고 바로 Final Answer로

---

## 시나리오 3: 본문만 제공 (콘텐츠 처리)

**입력**: "(긴 뉴스 기사 본문)"

```
User: "오늘 서울시는 미세먼지 저감 대책의 일환으로..."
         │
         ▼
┌─────────────────┐
│Intent Classifier│ ──► LLM 호출 (1회)
│                 │     intent = "new_question"
│                 │     rewritten_query = "(콘텐츠 분석/처리)"
│                 │     needs_tool = false  ← 질문 없이 본문만
└────────┬────────┘
         │ needs_tool = false
         ▼
    ┌─────────┐
    │  Final  │ ──► LLM 호출 (1회)
    │ Answer  │     GENERAL_CONVERSATION_PROMPT 사용
    │         │     - 콘텐츠 유형 파악 (기사, 코드, 데이터 등)
    │         │     - 핵심 인사이트 제공
    │         │     - 추가 작업 제안 (번역, 요약, 상세 설명 등)
    └────┬────┘
         │
         ▼
      __end__
```

**LLM 호출**: 2회 (Intent 1회 + Final Answer 1회)

---

## 시나리오 4: 후속 질문 (컨텍스트 보존)

**입력**: "더 있어?"

```
User: "영등포 견과류 알레르기 안전한 맛집 추천해줘"
Assistant: "A식당, B식당을 추천드립니다..."

User: "더 있어?"
         │
         ▼
┌─────────────────┐
│Intent Classifier│ ──► LLM 호출 (1회)
│                 │     intent = "follow_up"
│                 │     constraints = "위치(영등포), 제약사항(견과류 알레르기)"
│                 │     rewritten_query = "영등포 견과류 알레르기 안전한 다른 맛집 추천"
│                 │     needs_tool = true
└────────┬────────┘
         │
         ▼
    ┌─────────┐
    │ Planner │ ──► 재작성된 쿼리로 계획 수립
    └────┬────┘
         │
         ▼
       (이하 동일)
```

**핵심**: 이전 대화의 제약조건(위치, 알레르기 등)이 `rewritten_query`에 보존됨

---

## 시나리오 5: 다단계 작업 (도구 체이닝)

**입력**: "LangGraph가 뭔지 검색하고 요약해줘"

```
User: "LangGraph가 뭔지 검색하고 요약해줘"
         │
         ▼
┌─────────────────┐
│Intent Classifier│ ──► intent = "new_question", needs_tool = true
└────────┬────────┘
         │
         ▼
    ┌─────────┐
    │ Planner │ ──► plan = [
    │         │       {"step_id": 1, "tool": "web_search", "input": "LangGraph"},
    │         │       {"step_id": 2, "tool": "summarize", "input_from": "step_1"}
    │         │     ]
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │Executor │ ──► web_search("LangGraph") 실행
    │ Step 1  │     past_steps = [{step_id: 1, status: "success", output: "..."}]
    └────┬────┘
         │ plan에 step 2 남음
         ▼
    ┌─────────┐
    │Executor │ ──► summarize(step_1의 output) 실행
    │ Step 2  │     past_steps = [{...}, {step_id: 2, status: "success", ...}]
    └────┬────┘
         │ plan이 비었음
         ▼
    ┌─────────┐
    │  Final  │ ──► result = "LangGraph는 LangChain 기반의..."
    │ Answer  │
    └────┬────┘
         │
         ▼
      __end__
```

**LLM 호출**: 3회 (Intent 1회 + Planner 1회 + Final Answer 1회)
**참고**: Executor는 LLM을 호출하지 않음 (도구 실행만)

---

## 시나리오 6: 실패 및 재계획

```
User: "서울 날씨 알려줘"
         │
         ▼
┌─────────────────┐
│Intent Classifier│ ──► needs_tool = true
└────────┬────────┘
         │
         ▼
    ┌─────────┐
    │ Planner │ ──► plan = [{"tool": "get_weather", "input": "서울"}]
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │Executor │ ──► get_weather("서울") 실행
    │         │     ⚠️ API 오류 발생!
    │         │     past_steps = [{
    │         │       "status": "failure",
    │         │       "output": "API rate limit exceeded"
    │         │     }]
    └────┬────┘
         │ status == "failure"
         ▼
    ┌───────────┐
    │Re-planner │ ──► LLM 호출 (1회)
    │           │     실패 분석: "API 한도 초과"
    │           │     대안: web_search로 날씨 검색
    │           │     plan = [{"tool": "web_search", "input": "서울 날씨"}]
    │           │     replan_count = 1
    └────┬──────┘
         │
         ▼
    ┌─────────┐
    │Executor │ ──► web_search("서울 날씨") 실행
    │         │     past_steps = [{...}, {status: "success", ...}]
    └────┬────┘
         │ plan이 비었음
         ▼
    ┌─────────┐
    │  Final  │ ──► result = "서울의 현재 날씨는..."
    │ Answer  │
    └────┬────┘
         │
         ▼
      __end__
```

**LLM 호출**: 4회 (Intent 1회 + Planner 1회 + Re-planner 1회 + Final Answer 1회)

---

## 시나리오 7: Fail-Closed (JSON 파싱 실패)

```
User: "복잡한 요청"
         │
         ▼
┌─────────────────┐
│Intent Classifier│ ──► needs_tool = true
└────────┬────────┘
         │
         ▼
    ┌─────────┐
    │ Planner │ ──► LLM 호출
    │         │     ⚠️ JSON 파싱 실패!
    │         │     (LLM이 잘못된 형식 반환)
    └────┬────┘
         │ error 상태 설정
         ▼
    ┌───────────┐
    │   Error   │ ──► 즉시 중단
    │  Handler  │     result = "실행이 중단되었습니다: Invalid JSON"
    └────┬──────┘
         │
         ▼
      __end__
```

---

## 조건부 엣지 로직

### after_intent_classifier: Intent Classifier 후 분기

```python
def after_intent_classifier(state: PTEState) -> str:
    if state.get("needs_tool", True):
        return "planner"
    return "final_answer"
```

### after_planner: Planner 후 분기

```python
def after_planner(state: PTEState) -> str:
    if state.get("error"):
        return "error_handler"
    if state.get("plan"):
        return "executor"
    return "final_answer"
```

### after_executor: Executor 후 분기

```python
def after_executor(state: PTEState) -> str:
    if not state.get("past_steps"):
        return "final_answer"

    last_step = state["past_steps"][-1]

    if last_step["status"] == "failure":
        return "replanner"

    if state["plan"]:  # 남은 step이 있으면
        return "executor"

    return "final_answer"
```

### after_replanner: Re-planner 후 분기

```python
def after_replanner(state: PTEState) -> str:
    if state.get("error"):
        return "error_handler"
    return "executor"
```

---

## LLM 호출 횟수 비교

| 시나리오 | PTE |
|----------|-----|
| 잡담/간단한 대화 | 2회 (intent + final) |
| 도구 1개 사용 | 3회 (intent + planner + final) |
| 도구 3개 사용 | 3회 (intent + planner + final) |
| 본문만 제공 (콘텐츠 처리) | 2회 (intent + final) |
| 실패 1회 복구 | 4회 (intent + planner + replanner + final) |

**핵심**: 도구 개수가 늘어나도 LLM 호출 횟수는 증가하지 않음 (Executor는 LLM 미사용)

---

## 핵심 설계 원칙

### 1. 의도 우선 분류 (Intent-First)

```
Intent Classifier
─────────────────
- 사용자 의도 파악 (new_question, follow_up, chitchat 등)
- 컨텍스트 기반 쿼리 재작성 (제약조건 보존)
- 도구 필요 여부 결정 (불필요시 Planner 스킵)
```

### 2. 결정과 집행의 분리

```
Planner (결정)              Executor (집행)
─────────────────           ─────────────────
- 무엇을 할지 결정           - 결정된 대로만 실행
- 도구 선택                 - 도구 실행
- 순서 결정                 - 결과 기록
- LLM 사용 ✓                - LLM 사용 ✗
```

### 3. Fail-Closed 정책

| 상황 | 동작 |
|------|------|
| JSON 파싱 실패 | 즉시 중단, Error Handler |
| Schema validation 실패 | 즉시 중단, Error Handler |
| 허용되지 않은 tool | 즉시 중단, Error Handler |
| 재계획 한도 초과 | 즉시 중단, Error Handler |

### 4. 감사 가능성 (Audit Trail)

`past_steps`에 모든 실행 기록이 남음:

```python
past_steps = [
    {
        "step": {"step_id": 1, "tool": "web_search", "input": "..."},
        "status": "success",
        "output": "검색 결과..."
    },
    {
        "step": {"step_id": 2, "tool": "summarize", "input_from": "step_1"},
        "status": "failure",
        "output": "Error: timeout"
    },
    # Re-plan 후 새로운 시도
    {
        "step": {"step_id": 3, "tool": "summarize", "input_from": "step_1"},
        "status": "success",
        "output": "요약 결과..."
    }
]
```

---

## Final Answer 프롬프트

### 도구 결과 있는 경우 (FINAL_ANSWER_PROMPT)

- 실행 결과를 자연스럽게 정리
- 원본 입력과 재작성된 쿼리를 함께 참조
- 사용자 언어로 응답

### 도구 결과 없는 경우 (GENERAL_CONVERSATION_PROMPT)

1. 명시적 지시가 있으면 → 해당 작업 수행 (번역, 요약, 분석 등)
2. 본문만 있으면 → 콘텐츠 분석 + 추가 작업 제안
3. 단순 대화면 → 자연스럽게 응답

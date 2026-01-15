# Plan-then-Execute (PTE) 에이전트 플로우

## 전체 그래프 구조

```
                    ┌────────────────┐
                    │   __start__    │
                    └───────┬────────┘
                            │
                            ▼
                    ┌────────────────┐
                    │    Planner     │ ← LLM: 실행 계획 생성 (1회)
                    │   (컴파일러)    │
                    └───────┬────────┘
                            │
                    ┌───────┴───────┐
                    │               │
               (JSON 성공)      (JSON 실패)
                    │               │
                    ▼               ▼
            ┌──────────────┐  ┌─────────────┐
            │ has_plan?    │  │   Error     │
            └──────┬───────┘  │  Handler    │
                   │          └──────┬──────┘
           ┌───────┴───────┐         │
           │               │         ▼
        (plan 있음)    (plan 없음)  __end__
           │               │
           ▼               ▼
    ┌────────────┐  ┌─────────────┐
    │  Executor  │  │   Final     │
    │  (런타임)   │  │   Answer    │
    └─────┬──────┘  └──────┬──────┘
          │                │
          ▼                ▼
    ┌─────────────┐     __end__
    │ check_result│
    └─────┬───────┘
          │
    ┌─────┴─────┐
    │           │
 (성공)      (실패)
    │           │
    │           ▼
    │    ┌─────────────┐
    │    │ Re-planner  │ ← LLM: 계획 수정
    │    └──────┬──────┘
    │           │
    │    ┌──────┴──────┐
    │    │             │
    │ (재계획)    (한계 초과)
    │    │             │
    │    ▼             ▼
    │  Executor  ┌─────────────┐
    │    ↑       │   Error     │
    │    │       │  Handler    │
    │    └───────┴──────┬──────┘
    │                   │
    └───────┬───────────┘
            │
            ▼
     has_more_steps?
            │
    ┌───────┴───────┐
    │               │
 (더 있음)       (완료)
    │               │
    ▼               ▼
 Executor    Final Answer
```

---

## 노드별 역할

| 노드 | LLM 사용 | 역할 | 입력 | 출력 |
|------|----------|------|------|------|
| Planner | O (1회) | 사용자 요청 → 실행 계획 변환 | `input` | `plan` |
| Executor | X | plan의 step 실행 | `plan[0]` | `past_steps` |
| Re-planner | O (실패 시) | 실패 분석 및 계획 수정 | `plan`, `past_steps` | `plan` (수정) |
| Final Answer | O (1회) | 실행 결과 정리 | `past_steps` | `result` |
| Error Handler | X | Fail-closed 처리 | `error` | `result` |

---

## State 스키마

```python
class PTEState(TypedDict):
    # 입력
    input: str                      # 사용자 요청 원문

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

## 시나리오 1: 단순 질문 (도구 1개)

**입력**: "서울 날씨 알려줘"

```
User: "서울 날씨 알려줘"
         │
         ▼
    ┌─────────┐
    │ Planner │ ──► LLM 호출 (1회)
    │         │     plan = [
    │         │       {"step_id": 1, "tool": "get_weather", "input": "서울"}
    │         │     ]
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │Executor │ ──► get_weather("서울") 실행
    │         │     past_steps = [{
    │         │       "step": {"step_id": 1, "tool": "get_weather", ...},
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

**LLM 호출**: 2회 (Planner 1회 + Final Answer 1회)

---

## 시나리오 2: 다단계 작업 (도구 여러 개)

**입력**: "LangGraph가 뭔지 검색하고 요약해줘"

```
User: "LangGraph가 뭔지 검색하고 요약해줘"
         │
         ▼
    ┌─────────┐
    │ Planner │ ──► LLM 호출 (1회)
    │         │     plan = [
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
    │  Final  │ ──► LLM 호출 (1회)
    │ Answer  │     result = "LangGraph는 LangChain 기반의..."
    └────┬────┘
         │
         ▼
      __end__
```

**LLM 호출**: 2회 (Planner 1회 + Final Answer 1회)
**참고**: Executor는 LLM을 호출하지 않음 (코드 실행만)

---

## 시나리오 3: 실패 및 재계획

**입력**: "날씨 API가 오류 발생하는 경우"

```
User: "서울 날씨 알려줘"
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

**LLM 호출**: 3회 (Planner 1회 + Re-planner 1회 + Final Answer 1회)

---

## 시나리오 4: Fail-Closed (JSON 파싱 실패)

```
User: "복잡한 요청"
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

**LLM 호출**: 1회 (Planner만, 실패로 종료)

---

## 조건부 엣지 로직

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
    last_step = state["past_steps"][-1]

    if last_step["status"] == "failure":
        return "replanner"

    if state["plan"]:  # 남은 step이 있으면
        return "executor"

    return "final_answer"
```

### after_replanner: Re-planner 후 분기

```python
MAX_REPLAN = 3

def after_replanner(state: PTEState) -> str:
    if state["replan_count"] >= MAX_REPLAN:
        return "error_handler"
    if state.get("error"):
        return "error_handler"
    return "executor"
```

---

## LLM 호출 횟수 비교

| 시나리오 | ReAct (기존) | PTE |
|----------|--------------|-----|
| 단순 대화 | 2회 (router + agent) | 2회 (planner + final) |
| 도구 1개 사용 | 3회 (router + agent×2) | 2회 |
| 도구 3개 사용 | 5회 (router + agent×4) | 2회 |
| 실패 1회 복구 | N/A | 3회 (+re-planner) |

**핵심**: 도구 개수가 늘어나도 PTE는 LLM 호출이 증가하지 않음

---

## 핵심 설계 원칙

### 1. 결정과 집행의 분리

```
Planner (결정)              Executor (집행)
─────────────────           ─────────────────
- 무엇을 할지 결정           - 결정된 대로만 실행
- 도구 선택                 - 도구 실행
- 순서 결정                 - 결과 기록
- LLM 사용 ✓                - LLM 사용 ✗
```

### 2. Fail-Closed 정책

| 상황 | 동작 |
|------|------|
| JSON 파싱 실패 | 즉시 중단, Error Handler |
| Schema validation 실패 | 즉시 중단, Error Handler |
| 허용되지 않은 tool | 즉시 중단, Error Handler |
| 재계획 한도 초과 | 즉시 중단, Error Handler |

### 3. 감사 가능성 (Audit Trail)

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

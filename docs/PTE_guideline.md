# 📘 LangGraph 기반 Plan-then-Execute (P-t-E) 개발 가이드라인

> 목적  
> LangGraph를 사용하여 **예측 가능하고, 감사 가능하며, 보안 친화적인  
> Plan-then-Execute 에이전트 아키텍처**를 구현한다.

---

## 0. 핵심 설계 철학 (절대 위반 금지)

1. 결정(Planning)과 집행(Execution)을 시간적으로 분리한다
2. 제어 흐름(Control Flow)은 **그래프(State + Edge)** 로만 결정한다
3. 외부 데이터 접근은 **Executor에서만** 허용한다
4. Executor는 **판단하지 않는다**
5. 실패는 기록하고, 해결은 **Re-planner**가 한다
6. 구조화 출력(JSON)이 깨지면 **Fail-Closed (실행 금지)**

---

## 1. 전체 아키텍처 개요

```text
User Input
   ↓
[ Planner Node ]          (LLM, 1회)
   ↓
[ Execution Loop ]
   ├─ Executor Node       (Code / Tool)
   ├─ (조건) Re-planner   (LLM)
   └─ 반복
   ↓
[ Final Answer Node ]     (LLM)
```
---

## 2. State 설계 (LangGraph의 핵심)
### 2.1 최소 State 스키마
```from typing import TypedDict, List, Any

class AgentState(TypedDict):
    input: str                 # 사용자 요청
    plan: List[dict]           # 남은 실행 계획
    past_steps: List[dict]     # 실행 로그 (사실만)
    result: Any | None         # 최종 결과
```
### 2.2 State 설계 원칙

- plan은 반드시 구조화(JSON)

- past_steps에는 판단/의미 해석 금지

- 상태는 사실(fact)만 담는다
---
## 3. Planner Node 가이드라인
### 3.1 역할 정의

- Planner = 컴파일러

- 사용자 목표 해석

- 사용 가능한 tool을 고려한 실행 가능한 plan 생성

- 외부 데이터 접근 ❌

- tool 실행 ❌

### 3.2 입력 / 출력 계약

### 입력

- `state.input`

- 정적 tool manifest

### 출력

- `state.plan (필수, JSON)`

```{
  "steps": [
    {
      "step_id": 1,
      "tool": "web_search",
      "input": "plan then execute llm agent security"
    }
  ]
}
```

### 3.3 Planner 필수 규칙

- 그래프 시작 시 1회만 호출

- JSON Schema validation 실패 시 실행 금지

- task 필드는 설명용(optional)

## 4. Executor Node 가이드라인
### 4.1 역할 정의

> Executor = 런타임

- plan에 정의된 step을 그대로 실행

- 결과 기록

- 판단 ❌

- 전략 수정 ❌

### 4.2 Executor 기본 루프 예시
```def executor(state: AgentState) -> AgentState:
    step = state["plan"].pop(0)

    try:
        output = run_tool(step)
        status = "success"
    except Exception as e:
        output = str(e)
        status = "failure"

    state["past_steps"].append({
        "step": step,
        "status": status,
        "output": output
    })

    return state
```
### 4.3 Executor 필수 규칙

- step에 명시된 tool만 사용

- task 필드는 읽지 않아도 실행 가능해야 함

- 실패 시 기록만 하고 판단하지 않음

## 5. Conditional Edge 설계
### 5.1 기본 라우팅
```def route(state: AgentState):
    if state.get("result") is not None:
        return "final"
    if state["plan"]:
        return "execute"
    return "final"
```
### 5.2 실패 시 Re-plan 분기
```def should_replan(state: AgentState):
    last = state["past_steps"][-1]
    return last["status"] == "failure"
```
## 6. Re-planner Node 가이드라인
### 6.1 Re-planner의 역할

- 실패 원인 분석

- 기존 plan을 부분 수정

- 즉흥 실행 금지

### 6.2 입력 / 출력

### 입력

- `state.plan`

- `state.past_steps`

### 출력

- 수정된 `state.plan` (patch 방식 권장)
```
{
  "patch": [
    {
      "replace_step_id": 2,
      "new_step": {
        "step_id": 2,
        "tool": "chunk_and_summarize",
        "input_from": "step_1"
      }
    }
  ]
}
```
### 6.3 Re-planner 안전 규칙

- 최대 재계획 횟수 제한

- 새로운 고위험 tool 추가 금지

- 필요 시 Human-in-the-Loop로 승격

## 7. Tool 설계 가이드라인
### 7.1 Tool은 반드시 분리한다
| 목적     | Tool         |
| ------ | ------------ |
| 검색     | web_search   |
| 다운로드   | fetch_pdf    |
| 파싱     | parse_pdf    |
| RAG 검색 | rag_retrieve |
| 요약     | summarize    |

❌ `search_and_read()` 같은 블랙박스 tool 금지

### 8. RAG 통합 규칙

- RAG는 Executor가 호출하는 tool

- Planner는 “RAG를 쓸지 말지”만 결정

- RAG 결과는 명령이 아닌 데이터

## 9. LLM 호출 최소화 전략
| 단계           | 권장 모델       |
| ------------ | ----------- |
| Planner      | 대형 모델 (추론력) |
| Re-planner   | 중형 모델       |
| Final Answer | 소형 모델       |

Executor는 비-LLM(코드) 구현 권장

## 10. Fail-Closed 정책 (중요)

아래 중 하나라도 발생하면 즉시 중단:

- Planner JSON 파싱 실패

- Schema validation 실패

- 허용되지 않은 tool 등장

- 무한 재시도 루프 감지

## 11. Final Answer Node 가이드라인

>Final Answer = 결과 정리 전용

- `past_steps`, `result`만 사용

- 새로운 tool 호출 ❌

- 새로운 plan 생성 ❌

## 12. 출시 전 체크리스트

- Planner는 외부 데이터 접근 불가

- Executor는 판단하지 않음

- 모든 실행은 plan에 명시됨

- JSON 실패 시 실행 금지

- tool 권한은 step 단위

- re-plan 횟수 제한 존재

## 13. 최종 요약

>LangGraph는 P-t-E를
프롬프트 규칙이 아니라
아키텍처로 강제할 수 있는 프레임워크다.
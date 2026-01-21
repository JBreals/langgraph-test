# PTE Agent 비동기 전환 계획

## 개요

현재 하이브리드 방식(이벤트 루프 + ThreadPoolExecutor)에서 완전 비동기 방식으로 전환하기 위한 세부 계획.

### 전환 목표
- 모든 I/O 작업을 단일 이벤트 루프에서 처리
- `run_in_executor` 제거
- 리소스 효율성 및 동시성 개선

### 전제 조건
- Python 3.11+
- LangChain/LangGraph async 지원 (`ainvoke`, `astream`)
- Tavily `AsyncTavilyClient` 지원 확인됨
- httpx `AsyncClient` 사용

---

## 파일별 변환 계획

### 1. Tools Layer

#### `src/tools/web_search.py`
**난이도**: 쉬움

```python
# Before
from tavily import TavilyClient

def web_search(...) -> str:
    client = TavilyClient(api_key=settings.tavily_api_key)
    response = client.search(...)
    return result

def _extract_webpages(client, urls: list[str]) -> str:
    response = client.extract(urls=urls)
    return content

# After
from tavily import AsyncTavilyClient

async def web_search(...) -> str:
    client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    response = await client.search(...)
    return result

async def _extract_webpages(client: AsyncTavilyClient, urls: list[str]) -> str:
    response = await client.extract(urls=urls)
    return content
```

**체크리스트**:
- [ ] `TavilyClient` → `AsyncTavilyClient`
- [ ] `client.search()` → `await client.search()`
- [ ] `client.extract()` → `await client.extract()`
- [ ] 함수 시그니처 `def` → `async def`

---

#### `src/tools/rag_retrieve.py`
**난이도**: 쉬움

```python
# Before
import httpx

def _get_embedding(text: str) -> list[float] | None:
    with httpx.Client() as client:
        response = client.post(...)
    return embedding

def rag_retrieve(...) -> str:
    embedding = _get_embedding(query)
    # Pinecone 호출
    return results

# After
import httpx

async def _get_embedding(text: str) -> list[float] | None:
    async with httpx.AsyncClient() as client:
        response = await client.post(...)
    return embedding

async def rag_retrieve(...) -> str:
    embedding = await _get_embedding(query)
    # Pinecone async 호출 (pinecone-client 3.x 지원)
    return results
```

**체크리스트**:
- [ ] `httpx.Client` → `httpx.AsyncClient`
- [ ] `client.post()` → `await client.post()`
- [ ] Pinecone async 지원 확인 (`index.query()` → `await index.query()`)
- [ ] 캐시 통합 시 async 호환성 확인

---

#### `src/tools/query_enhancer.py`
**난이도**: 쉬움

```python
# Before
def enhance_query(...) -> str:
    response = llm.invoke([...])
    return enhanced_query

# After
async def enhance_query(...) -> str:
    response = await llm.ainvoke([...])
    return enhanced_query
```

**체크리스트**:
- [ ] `llm.invoke()` → `await llm.ainvoke()`
- [ ] 함수 시그니처 변경

---

### 2. Nodes Layer

모든 노드 파일에 동일한 패턴 적용.

#### `src/pte/nodes/intent_classifier.py`
```python
# Before
def intent_classifier_node(state: PTEState) -> dict:
    response = llm.invoke([...])
    return {...}

# After
async def intent_classifier_node(state: PTEState) -> dict:
    response = await llm.ainvoke([...])
    return {...}
```

#### `src/pte/nodes/planner.py`
```python
# Before
def planner_node(state: PTEState) -> dict:
    response = llm.invoke([...])
    return {...}

# After
async def planner_node(state: PTEState) -> dict:
    response = await llm.ainvoke([...])
    return {...}
```

#### `src/pte/nodes/executor.py`
```python
# Before
def executor_node(state: PTEState) -> dict:
    # tool 호출
    result = tool_func(...)
    return {...}

# After
async def executor_node(state: PTEState) -> dict:
    # async tool 호출
    result = await tool_func(...)
    return {...}
```

**주의**: executor에서 호출하는 모든 tool이 async여야 함.

#### `src/pte/nodes/replanner.py`
```python
async def replanner_node(state: PTEState) -> dict:
    response = await llm.ainvoke([...])
    return {...}
```

#### `src/pte/nodes/final_answer.py`
```python
async def final_answer_node(state: PTEState) -> dict:
    response = await llm.ainvoke([...])
    return {"result": response.content}
```

**노드 체크리스트**:
- [ ] `intent_classifier.py` - `ainvoke` 적용
- [ ] `planner.py` - `ainvoke` 적용
- [ ] `executor.py` - async tool 호출
- [ ] `replanner.py` - `ainvoke` 적용
- [ ] `final_answer.py` - `ainvoke` 적용

---

### 3. Graph Layer

#### `src/pte/graph.py`
**난이도**: 중간

```python
# Before
from langgraph.graph import StateGraph

def get_pte_graph():
    graph = StateGraph(PTEState)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("planner", planner_node)
    # ...
    return graph.compile()

# After
from langgraph.graph import StateGraph

def get_pte_graph():
    graph = StateGraph(PTEState)
    # async 노드 등록 (LangGraph가 자동 감지)
    graph.add_node("intent_classifier", intent_classifier_node)  # async def
    graph.add_node("planner", planner_node)  # async def
    # ...
    return graph.compile()
```

**참고**: LangGraph는 async 노드를 자동 감지하여 처리함. 노드 등록 코드는 변경 불필요.

**체크리스트**:
- [ ] 모든 노드가 async인지 확인
- [ ] 조건부 엣지 함수가 async 필요한지 확인

---

### 4. API Layer

#### `src/api/routes/chat.py`
**난이도**: 중간

```python
# Before (하이브리드)
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)

@router.post("/chat")
async def chat(request: ChatRequest):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        graph.invoke,
        initial_state
    )
    return {"response": result["result"]}

# After (순수 async)
@router.post("/chat")
async def chat(request: ChatRequest):
    result = await graph.ainvoke(initial_state)
    return {"response": result["result"]}
```

#### 스트리밍 엔드포인트
```python
# Before
@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def generate():
        loop = asyncio.get_event_loop()
        # 동기 stream을 스레드에서 실행
        for event in await loop.run_in_executor(executor, list, graph.stream(state)):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")

# After
@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    async def generate():
        async for event in graph.astream(initial_state):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**체크리스트**:
- [ ] `ThreadPoolExecutor` 제거
- [ ] `run_in_executor` 제거
- [ ] `graph.invoke()` → `await graph.ainvoke()`
- [ ] `graph.stream()` → `async for ... in graph.astream()`

---

### 5. Entry Point

#### `main.py` (CLI)
**난이도**: 쉬움

```python
# Before
def run_agent(...) -> tuple[str, str | None]:
    graph = get_pte_graph()
    final_state = graph.invoke(initial_state)
    return result, rewritten

def main():
    while True:
        result, rewritten = run_agent(user_input, history)
        print(f"Agent: {result}")

# After
import asyncio

async def run_agent(...) -> tuple[str, str | None]:
    graph = get_pte_graph()
    final_state = await graph.ainvoke(initial_state)
    return result, rewritten

async def main():
    while True:
        result, rewritten = await run_agent(user_input, history)
        print(f"Agent: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

**스트리밍 모드**:
```python
async def run_agent_stream(...):
    graph = get_pte_graph()
    async for event in graph.astream(initial_state):
        for node_name, node_output in event.items():
            print(f"📍 Node: {node_name}")
            # ...
```

---

## 의존성 업데이트

### `requirements.txt` 또는 `pyproject.toml`

```txt
# 기존
tavily-python>=0.3.0
httpx>=0.25.0
langchain>=0.1.0
langgraph>=0.0.20

# 확인 필요
pinecone-client>=3.0.0  # async 지원 버전
```

### Pinecone Async 지원

Pinecone Python SDK 3.x부터 async 지원:
```python
from pinecone import Pinecone

pc = Pinecone(api_key="...")
index = pc.Index("index-name")

# Async query
results = await index.query(vector=[...], top_k=5)
```

---

## 전환 순서 (권장)

### Phase 1: Tools Layer
1. `query_enhancer.py` - 가장 단순
2. `rag_retrieve.py` - httpx async
3. `web_search.py` - Tavily async

### Phase 2: Nodes Layer
4. `intent_classifier.py`
5. `planner.py`
6. `replanner.py`
7. `final_answer.py`
8. `executor.py` - tools 의존

### Phase 3: Graph & API
9. `graph.py` - 노드 통합 확인
10. `routes/chat.py` - API 전환
11. `main.py` - CLI 전환

### Phase 4: 정리
12. `ThreadPoolExecutor` 관련 코드 제거
13. 불필요한 sync wrapper 제거
14. 테스트 코드 async 전환

---

## 테스트 전략

### 단위 테스트
```python
import pytest

@pytest.mark.asyncio
async def test_web_search():
    result = await web_search("test query", time_sensitive="none")
    assert result is not None

@pytest.mark.asyncio
async def test_intent_classifier():
    state = {...}
    result = await intent_classifier_node(state)
    assert "intent" in result
```

### 통합 테스트
```python
@pytest.mark.asyncio
async def test_full_graph():
    graph = get_pte_graph()
    result = await graph.ainvoke(initial_state)
    assert result["result"] is not None
```

### pytest 설정
```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 롤백 계획

문제 발생 시 하이브리드 방식으로 롤백:

1. 노드를 sync로 유지
2. `run_in_executor`로 감싸서 호출
3. 점진적으로 async 전환 재시도

```python
# 롤백 패턴
async def chat(request: ChatRequest):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        graph.invoke,  # sync 유지
        initial_state
    )
    return {"response": result["result"]}
```

---

## 예상 작업량

| 영역 | 파일 수 | 예상 난이도 |
|------|--------|------------|
| Tools | 3 | 쉬움 |
| Nodes | 5 | 쉬움 |
| Graph | 1 | 중간 |
| API | 2 | 중간 |
| CLI | 1 | 쉬움 |
| Tests | 다수 | 중간 |

**총 예상**: 핵심 전환 ~12개 파일

---

## 참고 자료

- [LangGraph Async Documentation](https://langchain-ai.github.io/langgraph/)
- [Tavily Python SDK](https://docs.tavily.com/docs/python-sdk/tavily-search/getting-started)
- [httpx Async Client](https://www.python-httpx.org/async/)
- [Pinecone Python SDK v3](https://docs.pinecone.io/docs/python-client)

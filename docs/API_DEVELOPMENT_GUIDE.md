# PTE Agent API 개발 가이드라인

## 1. 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│                        Client                               │
│                   (Web, Mobile, CLI)                        │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP / SSE
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Server                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │   Routes    │  │ Middleware  │  │   Schemas   │          │
│  │  /chat      │  │  CORS       │  │  Request    │          │
│  │  /sessions  │  │  Logging    │  │  Response   │          │
│  │  /health    │  │  Error      │  │  Error      │          │
│  └──────┬──────┘  └─────────────┘  └─────────────┘          │
│         │                                                    │
│  ┌──────▼──────────────────────────────────────────┐        │
│  │              Services Layer                      │        │
│  │  ┌─────────────────┐  ┌─────────────────┐       │        │
│  │  │  AgentService   │  │ SessionService  │       │        │
│  │  │  - run()        │  │  - get/create   │       │        │
│  │  │  - stream()     │  │  - add_message  │       │        │
│  │  └────────┬────────┘  └────────┬────────┘       │        │
│  └───────────┼────────────────────┼────────────────┘        │
│              │                    │                          │
│  ┌───────────▼────────────────────▼────────────────┐        │
│  │              Storage Layer                       │        │
│  │  ┌─────────────────────────────────────────┐    │        │
│  │  │         SessionStorage (ABC)            │    │        │
│  │  │  ┌──────────┐  ┌──────────┐  ┌────────┐ │    │        │
│  │  │  │  Memory  │  │ Postgres │  │ Redis  │ │    │        │
│  │  │  └──────────┘  └──────────┘  └────────┘ │    │        │
│  │  └─────────────────────────────────────────┘    │        │
│  └─────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    PTE Agent Core                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                  LangGraph                           │    │
│  │  intent_classifier → planner → executor → final     │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │    Tools    │  │     LLM     │  │   Config    │          │
│  │  web_search │  │  OpenRouter │  │  Settings   │          │
│  │  calculator │  │             │  │             │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 레이어 책임

### 2.1 API Layer (`src/api/`)

| 컴포넌트 | 책임 | 하지 않는 것 |
|----------|------|-------------|
| **Routes** | HTTP 요청 수신, 응답 반환 | 비즈니스 로직 |
| **Schemas** | 요청/응답 유효성 검증 | 데이터 변환 로직 |
| **Middleware** | 횡단 관심사 (CORS, 로깅) | 비즈니스 규칙 |
| **Dependencies** | 의존성 주입, 싱글톤 관리 | 직접 인스턴스 생성 |

### 2.2 Service Layer (`src/services/`)

| 컴포넌트 | 책임 | 하지 않는 것 |
|----------|------|-------------|
| **AgentService** | 에이전트 실행 오케스트레이션 | HTTP 처리, 세션 저장 |
| **SessionService** | 세션 생명주기 관리 | 에이전트 로직 |

### 2.3 Storage Layer (`src/storage/`)

| 컴포넌트 | 책임 | 하지 않는 것 |
|----------|------|-------------|
| **SessionStorage** | 데이터 영속화 추상화 | 비즈니스 규칙 |
| **Memory/Redis/PG** | 구체적 저장소 구현 | 다른 저장소 로직 |

---

## 3. 코드 컨벤션

### 3.1 파일 구조

```python
"""모듈 설명.

상세 설명 (필요시).
"""

# 표준 라이브러리
import asyncio
from typing import Optional

# 서드파티
from fastapi import APIRouter
from pydantic import BaseModel

# 로컬
from src.services.agent_service import AgentService
```

### 3.2 클래스/함수 네이밍

```python
# 서비스: ~Service
class AgentService:
    pass

# 스토리지: ~Storage
class InMemorySessionStorage:
    pass

# 라우트 함수: 동사_명사
async def create_session():
    pass

async def get_session():
    pass

# 프라이빗: _prefix
def _build_initial_state():
    pass
```

### 3.3 비동기 처리

```python
# ✅ 올바른 방식: async 함수
async def get(self, session_id: str) -> Optional[Session]:
    async with self._lock:
        return self._sessions.get(session_id)

# ✅ 동기 코드를 async로 래핑
async def run(self, user_input: str) -> str:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: self._graph.invoke(initial_state)
    )
    return result

# ❌ 잘못된 방식: async 함수에서 blocking 호출
async def bad_example():
    time.sleep(1)  # 이러면 안 됨
```

### 3.4 에러 처리

```python
# API 레이어: HTTPException 사용
from fastapi import HTTPException

async def get_session(session_id: str):
    session = await session_service.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

# 서비스 레이어: 커스텀 예외 또는 ValueError
class SessionNotFoundError(Exception):
    pass

async def add_message(self, session_id: str, ...):
    session = await self._storage.get(session_id)
    if not session:
        raise SessionNotFoundError(f"Session not found: {session_id}")
```

---

## 4. API 설계 원칙

### 4.1 엔드포인트 구조

```
/health                              # 헬스체크 (인증 불필요)
/ready                               # 레디니스 (인증 불필요)

# 채팅
/api/v1/chat                         # POST - 동기 채팅
/api/v1/chat/stream                  # POST - 스트리밍 채팅 (SSE)
/api/v1/chat/cancel                  # POST - 스트리밍 요청 취소
/api/v1/chat/{message_id}/feedback   # POST - 피드백 제출

# 세션
/api/v1/sessions/{id}                # GET - 세션 정보 조회
/api/v1/sessions/{id}                # DELETE - 세션 삭제
/api/v1/sessions/{id}/messages       # GET - 대화 히스토리 조회
```

### 4.2 요청/응답 포맷

```python
# 채팅 요청
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None

# 채팅 응답
class ChatResponse(BaseModel):
    session_id: str
    message_id: str              # 피드백용 메시지 ID
    message: str
    created_at: datetime

# 피드백 요청
class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]  # 좋아요/싫어요
    comment: Optional[str] = None  # 추가 코멘트

# 취소 요청
class CancelRequest(BaseModel):
    request_id: str              # 스트리밍 요청 ID

# 대화 히스토리 응답
class MessagesResponse(BaseModel):
    session_id: str
    messages: list[MessageItem]
    total_count: int

class MessageItem(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    feedback: Optional[str] = None  # "up" | "down" | None

# 에러 응답
class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    code: str = "INTERNAL_ERROR"
```

### 4.3 SSE 스트리밍 이벤트

```
event: session
data: {"session_id": "uuid"}

event: node_end
data: {"node": "intent_classifier", "intent": "new_question", ...}

event: step
data: {"tool": "web_search", "status": "success", "output_preview": "..."}

event: final
data: {"result": "최종 답변..."}

event: done
data: {}

event: error
data: {"error": "에러 메시지"}
```

### 4.4 RAG 저장소 지정

```python
# ChatRequest에 rag_store 옵션 추가
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: Optional[str] = None
    rag_store: Optional[str] = None  # 특정 RAG 저장소 지정

# 사용 예시
POST /api/v1/chat
{
    "message": "제품 반품 정책이 어떻게 되나요?",
    "rag_store": "policy-docs"
}

# RAG 저장소 목록 응답
class RagStoreListResponse(BaseModel):
    stores: list[RagStoreInfo]

class RagStoreInfo(BaseModel):
    id: str              # 저장소 ID (예: "policy-docs")
    name: str            # 표시 이름 (예: "정책 문서")
    type: str            # opensearch | faiss | memory
    document_count: int  # 문서 수 (가능한 경우)
    description: str     # 설명
```

### 4.5 RAG 엔드포인트

```
# RAG 저장소 관리
GET /api/v1/rag/stores                # 사용 가능한 저장소 목록
GET /api/v1/rag/stores/{store_id}     # 저장소 상세 정보
```

---

## 5. 스토리지 추상화

### 5.1 인터페이스

```python
from abc import ABC, abstractmethod

class SessionStorage(ABC):
    @abstractmethod
    async def get(self, session_id: str) -> Optional[Session]:
        """세션 조회."""
        ...

    @abstractmethod
    async def save(self, session: Session) -> Session:
        """세션 저장/업데이트."""
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> bool:
        """세션 삭제."""
        ...

    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        """세션 존재 여부."""
        ...
```

### 5.2 구현 교체

```python
# dependencies.py
from src.config import settings

def get_storage() -> SessionStorage:
    if settings.storage_type == "redis":
        return RedisSessionStorage(settings.redis_url)
    elif settings.storage_type == "postgres":
        return PostgresSessionStorage(settings.database_url)
    else:
        return InMemorySessionStorage()
```

---

## 6. 의존성 주입

### 6.1 패턴

```python
from functools import lru_cache
from fastapi import Depends
from typing import Annotated

# 싱글톤
@lru_cache()
def get_storage() -> SessionStorage:
    return InMemorySessionStorage()

# 의존성 체인
def get_session_service(
    storage: Annotated[SessionStorage, Depends(get_storage)]
) -> SessionService:
    return SessionService(storage)

# 타입 별칭
SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]

# 라우트에서 사용
@router.post("/chat")
async def chat(
    request: ChatRequest,
    session_service: SessionServiceDep
):
    ...
```

---

## 7. 테스트 가이드라인

### 7.1 단위 테스트

```python
# tests/unit/test_session_service.py
import pytest
from src.storage.memory import InMemorySessionStorage
from src.services.session_service import SessionService

@pytest.fixture
def storage():
    return InMemorySessionStorage()

@pytest.fixture
def session_service(storage):
    return SessionService(storage)

@pytest.mark.asyncio
async def test_get_or_create_new_session(session_service):
    session = await session_service.get_or_create()
    assert session.id is not None
    assert len(session.messages) == 0
```

### 7.2 통합 테스트

```python
# tests/integration/test_chat_api.py
import pytest
from httpx import AsyncClient
from src.api.main import app

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_chat_endpoint(client):
    response = await client.post(
        "/api/v1/chat",
        json={"message": "안녕하세요"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "message" in data
```

---

## 8. 환경 변수

```bash
# .env

# API 설정
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=1
DEBUG=true

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# 스토리지
STORAGE_TYPE=memory  # memory | redis | postgres
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql://user:pass@localhost:5432/pte

# 세션
SESSION_TTL_HOURS=24
MAX_SESSIONS=1000

# RAG 저장소
RAG_STORES_CONFIG=./config/rag_stores.json  # 저장소 설정 파일
RAG_DEFAULT_STORE=default                    # 기본 저장소 ID

# 기존 설정
OPENROUTER_API_KEY=sk-or-v1-...
TAVILY_API_KEY=tvly-...
OPENSEARCH_URL=http://localhost:9200
```

### RAG 저장소 설정 파일 예시

```json
// config/rag_stores.json
{
  "stores": [
    {
      "id": "default",
      "name": "기본 문서",
      "type": "opensearch",
      "config": {
        "url": "http://localhost:9200",
        "index": "default-docs"
      }
    },
    {
      "id": "policy-docs",
      "name": "정책 문서",
      "type": "opensearch",
      "config": {
        "url": "http://localhost:9200",
        "index": "policy-docs"
      }
    },
    {
      "id": "product-docs",
      "name": "제품 문서",
      "type": "faiss",
      "config": {
        "index_path": "./faiss_indexes/products"
      }
    }
  ]
}
```

---

## 9. 프로덕션 체크리스트

### 배포 전 필수

- [ ] `DEBUG=false` 설정
- [ ] `CORS_ORIGINS` 특정 도메인으로 제한
- [ ] 스토리지를 Redis 또는 PostgreSQL로 변경
- [ ] 로깅 레벨 및 포맷 설정
- [ ] 헬스체크 엔드포인트 모니터링 연동

### 권장 사항

- [ ] Rate Limiting 구현
- [ ] 인증/인가 (JWT) 추가
- [ ] 메트릭 수집 (Prometheus)
- [ ] 분산 트레이싱 (OpenTelemetry)
- [ ] 컨테이너화 (Docker)

---

## 10. 디렉토리 생성 순서

```bash
# 1. 스토리지 레이어
mkdir -p src/storage
touch src/storage/__init__.py
touch src/storage/models.py
touch src/storage/base.py
touch src/storage/memory.py

# 2. 서비스 레이어
mkdir -p src/services
touch src/services/__init__.py
touch src/services/agent_service.py
touch src/services/session_service.py

# 3. API 레이어
mkdir -p src/api/routes src/api/schemas
touch src/api/__init__.py
touch src/api/main.py
touch src/api/dependencies.py
touch src/api/middleware.py
touch src/api/routes/__init__.py
touch src/api/routes/health.py
touch src/api/routes/chat.py
touch src/api/routes/sessions.py
touch src/api/schemas/__init__.py
touch src/api/schemas/requests.py
touch src/api/schemas/responses.py
touch src/api/schemas/errors.py
```

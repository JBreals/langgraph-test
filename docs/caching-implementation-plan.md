# 캐싱 시스템 구현 계획

## 목표
프로젝트에 인메모리 캐싱을 도입하여 API 비용 절감 및 응답 속도 개선

## 범위 (우선순위 1-2)
1. **임베딩 캐싱** (`_get_embedding`) - API 비용 높음, 결과 불변
2. **웹 검색/URL 추출 캐싱** (`web_search`, `_extract_webpages`) - 네트워크 지연 개선

---

## 파일 구조

```
src/
├── cache/                    # 신규 디렉토리
│   ├── __init__.py          # 공개 API, 팩토리 함수
│   ├── base.py              # 추상 인터페이스 (CacheBackend)
│   ├── memory.py            # 인메모리 캐시 (MemoryCache)
│   └── keys.py              # 캐시 키 생성 함수
├── config/
│   └── settings.py          # 캐시 설정 추가 (수정)
└── tools/
    ├── rag_retrieve.py      # 임베딩 캐시 통합 (수정)
    └── web_search.py        # 검색/URL 캐시 통합 (수정)
```

---

## 구현 단계

### Step 1: `src/cache/base.py` - 추상 인터페이스

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar, Generic

T = TypeVar("T")

@dataclass
class CacheEntry(Generic[T]):
    value: T
    created_at: datetime
    ttl_seconds: int | None = None

    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > self.ttl_seconds

@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    size: int = 0

class CacheBackend(ABC, Generic[T]):
    @abstractmethod
    def get(self, key: str) -> T | None: ...

    @abstractmethod
    def set(self, key: str, value: T, ttl_seconds: int | None = None) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> bool: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def get_stats(self) -> CacheStats: ...
```

### Step 2: `src/cache/memory.py` - 인메모리 구현

```python
import threading
from datetime import datetime

class MemoryCache(CacheBackend[T]):
    def __init__(
        self,
        default_ttl_seconds: int | None = 3600,
        max_size: int = 1000,
        cleanup_interval: int = 100,
    ):
        self._cache: dict[str, CacheEntry[T]] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl_seconds
        self._max_size = max_size
        # ... TTL 만료 정리, LRU eviction 구현
```

핵심 기능:
- Thread-safe (RLock)
- TTL 만료 자동 정리
- 최대 크기 제한 + LRU eviction

### Step 3: `src/cache/keys.py` - 캐시 키 생성

```python
import hashlib

def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())

def _hash_value(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]

def embedding_cache_key(text: str) -> str:
    """임베딩 캐시 키: emb:{hash}"""
    normalized = _normalize_text(text)
    return f"emb:{_hash_value(normalized)}"

def web_search_cache_key(query: str, search_depth: str, max_results: int) -> str:
    """검색 캐시 키: search:{hash}:{depth}:{max}"""
    normalized = _normalize_text(query)
    return f"search:{_hash_value(normalized, 12)}:{search_depth[:3]}:{max_results}"

def url_extract_cache_key(urls: list[str]) -> str:
    """URL 추출 캐시 키: url:{hash}"""
    normalized = sorted(url.rstrip("/") for url in urls)
    combined = "|".join(normalized)
    return f"url:{_hash_value(combined)}"
```

### Step 4: `src/cache/__init__.py` - 팩토리 및 싱글톤

```python
from src.config import settings

_caches: dict[str, CacheBackend] = {}

def get_cache(name: str) -> CacheBackend:
    if name not in _caches:
        _caches[name] = _create_cache(name)
    return _caches[name]

def _create_cache(name: str) -> CacheBackend:
    config = {
        "embedding": {"default_ttl_seconds": settings.cache_embedding_ttl, "max_size": 10000},
        "web_search": {"default_ttl_seconds": settings.cache_web_search_ttl, "max_size": 1000},
        "url_extract": {"default_ttl_seconds": settings.cache_url_extract_ttl, "max_size": 500},
    }
    return MemoryCache(**config.get(name, {}))
```

### Step 5: `src/config/settings.py` - 설정 추가

```python
# Cache Settings 섹션 추가
cache_enabled: bool = field(
    default_factory=lambda: os.getenv("CACHE_ENABLED", "true").lower() == "true"
)
cache_embedding_ttl: int = field(
    default_factory=lambda: int(os.getenv("CACHE_EMBEDDING_TTL", "86400"))  # 24시간
)
cache_web_search_ttl: int = field(
    default_factory=lambda: int(os.getenv("CACHE_WEB_SEARCH_TTL", "3600"))  # 1시간
)
cache_url_extract_ttl: int = field(
    default_factory=lambda: int(os.getenv("CACHE_URL_EXTRACT_TTL", "7200"))  # 2시간
)
```

### Step 6: `src/tools/rag_retrieve.py` - 임베딩 캐시 통합

```python
from src.cache import get_cache, embedding_cache_key

def _get_embedding(text: str) -> list[float] | None:
    if not settings.cache_enabled:
        return _get_embedding_from_api(text)

    cache = get_cache("embedding")
    key = embedding_cache_key(text)

    cached = cache.get(key)
    if cached is not None:
        return cached

    result = _get_embedding_from_api(text)
    if result is not None:
        cache.set(key, result)

    return result

def _get_embedding_from_api(text: str) -> list[float] | None:
    # 기존 API 호출 로직
```

### Step 7: `src/tools/web_search.py` - 검색/URL 캐시 통합

```python
from src.cache import get_cache, web_search_cache_key, url_extract_cache_key

def _extract_webpages(client, urls: list[str]) -> str:
    if settings.cache_enabled:
        cache = get_cache("url_extract")
        key = url_extract_cache_key(urls)
        cached = cache.get(key)
        if cached:
            return cached

    # ... API 호출 ...

    if settings.cache_enabled:
        cache.set(key, result)
    return result

def web_search(..., time_sensitive: str = "none") -> str:
    # time_sensitive="current"면 캐시 스킵
    should_cache = settings.cache_enabled and time_sensitive != "current"

    if should_cache:
        cache = get_cache("web_search")
        key = web_search_cache_key(enhanced_query, "advanced", 5)
        cached = cache.get(key)
        if cached:
            return f"[캐시됨] {cached}"

    # ... API 호출 ...

    if should_cache:
        cache.set(key, result)
    return result
```

---

## TTL 설정

| 캐시 | TTL | 이유 |
|------|-----|------|
| 임베딩 | 24시간 | 동일 텍스트 = 동일 임베딩 |
| 웹 검색 | 1시간 | 검색 결과 변동 가능 |
| URL 추출 | 2시간 | 페이지 내용 상대적 안정 |

---

## 캐시 제외 조건

- `time_sensitive="current"` → 웹 검색 캐시 스킵
- API 호출 실패 (None 반환) → 캐시 저장 안 함

---

## 검증 방법

### 1. 단위 테스트
```bash
# 캐시 모듈 테스트
python -m pytest tests/test_cache.py -v
```

### 2. 통합 테스트
```python
# 캐시 히트 확인
from src.cache import get_cache

cache = get_cache("embedding")
print(cache.get_stats())  # hits, misses, size 확인
```

### 3. 실제 동작 확인
```python
from src.tools.web_search import web_search

# 첫 호출: API 호출
result1 = web_search("요즘 핫한 카페", time_sensitive="none")

# 두 번째 호출: 캐시 히트 (결과에 [캐시됨] 표시)
result2 = web_search("요즘 핫한 카페", time_sensitive="none")

# time_sensitive="current"면 캐시 스킵
result3 = web_search("요즘 핫한 카페", time_sensitive="current")
```

---

## 파일 수정 요약

| 파일 | 작업 |
|------|------|
| `src/cache/__init__.py` | 신규 생성 |
| `src/cache/base.py` | 신규 생성 |
| `src/cache/memory.py` | 신규 생성 |
| `src/cache/keys.py` | 신규 생성 |
| `src/config/settings.py` | 캐시 설정 추가 |
| `src/tools/rag_retrieve.py` | 임베딩 캐시 통합 |
| `src/tools/web_search.py` | 검색/URL 캐시 통합 |

---

## 향후 확장 (Phase 2)
- Redis 백엔드 추가 (`src/cache/redis_cache.py`)
- `settings.cache_backend` 설정으로 백엔드 선택
- 쿼리 증강 캐싱 (`query_enhancer.py`)
- 의도 분류 캐싱 (`intent_classifier.py`)

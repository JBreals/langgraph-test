"""RAG Retrieve tool.

기존 벡터 스토어에서 문서를 검색합니다.
저장은 별도 ingestion 스크립트에서 수행 - 여기서는 검색만.
"""

import os
from src.config import settings
from src.tools.query_enhancer import maybe_enhance_query


# 벡터 스토어 타입 (환경변수로 설정)
RAG_STORE_TYPE = os.getenv("RAG_STORE_TYPE", "mock")  # mock, opensearch, faiss
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "langgraph-docs")
FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "./faiss_index")


def rag_retrieve(
    query: str,
    top_k: int = 3,
    context: str | None = None,
    from_previous_step: bool = False,
    history: list[dict[str, str]] | None = None,
) -> str:
    """벡터 스토어에서 관련 문서를 검색합니다.

    Args:
        query: 검색 쿼리
        top_k: 반환할 문서 수
        context: 원래 사용자 요청 (쿼리 증강에 사용)
        from_previous_step: 이전 도구 출력을 입력으로 사용하는 경우 True
        history: 대화 히스토리 (중복 방지에 사용)

    Returns:
        검색된 문서 내용
    """
    # LLM 기반 쿼리 증강 (대화 히스토리 포함)
    enhanced_query, was_enhanced = maybe_enhance_query(
        query, context, from_previous_step, history
    )

    store_type = RAG_STORE_TYPE.lower()

    # 증강 정보 prefix
    prefix = f"[검색어 자동 증강: {query} → {enhanced_query}]\n\n" if was_enhanced else ""

    if store_type == "opensearch":
        return prefix + _search_opensearch(enhanced_query, top_k)
    elif store_type == "faiss":
        return prefix + _search_faiss(enhanced_query, top_k)
    else:
        return prefix + _search_mock(enhanced_query, top_k)


def _search_mock(query: str, top_k: int) -> str:
    """Mock 검색 (테스트용)."""
    return f"[Mock RAG] '{query}' 검색 결과: 관련 문서를 찾지 못했습니다. (RAG_STORE_TYPE 환경변수 설정 필요)"


def _search_opensearch(query: str, top_k: int) -> str:
    """OpenSearch에서 검색."""
    try:
        from opensearchpy import OpenSearch

        client = OpenSearch(
            hosts=[OPENSEARCH_URL],
            http_compress=True,
            timeout=30,
        )

        # 벡터 검색 쿼리 (임베딩 필요)
        # 여기서는 간단히 텍스트 매칭 사용
        search_body = {
            "size": top_k,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["content", "title"],
                }
            },
        }

        response = client.search(index=OPENSEARCH_INDEX, body=search_body)

        hits = response.get("hits", {}).get("hits", [])

        if not hits:
            return f"'{query}'에 대한 문서를 찾지 못했습니다."

        results = []
        for i, hit in enumerate(hits, 1):
            source = hit.get("_source", {})
            content = source.get("content", "")[:500]
            title = source.get("title", "제목 없음")
            results.append(f"[{i}] {title}\n{content}")

        return "\n\n---\n\n".join(results)

    except ImportError:
        return "OpenSearch 클라이언트가 설치되지 않았습니다. (pip install opensearch-py)"
    except Exception as e:
        return f"OpenSearch 검색 실패: {e}"


def _search_faiss(query: str, top_k: int) -> str:
    """FAISS 인덱스에서 검색."""
    try:
        import faiss
        import json
        import numpy as np

        index_file = f"{FAISS_INDEX_PATH}/index.faiss"
        metadata_file = f"{FAISS_INDEX_PATH}/metadata.json"

        if not os.path.exists(index_file):
            return f"FAISS 인덱스 파일이 없습니다: {index_file}"

        # 인덱스 로드
        index = faiss.read_index(index_file)

        # 메타데이터 로드
        with open(metadata_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        # 쿼리 임베딩 생성 (OpenAI 임베딩 사용)
        query_embedding = _get_embedding(query)

        if query_embedding is None:
            return "임베딩 생성 실패"

        # 검색
        query_vector = np.array([query_embedding], dtype=np.float32)
        distances, indices = index.search(query_vector, top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(metadata):
                continue
            doc = metadata[idx]
            content = doc.get("content", "")[:500]
            title = doc.get("title", "제목 없음")
            results.append(f"[{i+1}] {title}\n{content}")

        if not results:
            return f"'{query}'에 대한 문서를 찾지 못했습니다."

        return "\n\n---\n\n".join(results)

    except ImportError:
        return "FAISS가 설치되지 않았습니다. (pip install faiss-cpu)"
    except Exception as e:
        return f"FAISS 검색 실패: {e}"


def _get_embedding(text: str) -> list[float] | None:
    """텍스트의 임베딩 벡터 생성."""
    try:
        from langchain_openai import OpenAIEmbeddings

        embeddings = OpenAIEmbeddings(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
        )

        return embeddings.embed_query(text)

    except Exception:
        return None

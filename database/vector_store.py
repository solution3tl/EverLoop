"""
向量数据库接口层 - 内存版实现（无需外部向量数据库）
知识库语义检索和长期记忆语义检索都走这里
生产环境可替换为 Chroma / Pinecone / PGVector
"""
import json
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class Document:
    content: str
    metadata: Dict
    embedding: Optional[List[float]] = None
    doc_id: str = ""


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _simple_embedding(text: str) -> List[float]:
    """
    简单的词频向量化（fallback，不依赖外部 Embedding 模型）
    生产环境应替换为真实 Embedding 模型（如 OpenAI text-embedding-3-small）
    """
    import hashlib
    dim = 128
    vec = [0.0] * dim
    words = text.lower().split()
    for word in words:
        # 用哈希将词映射到向量维度
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        idx = h % dim
        vec[idx] += 1.0

    # 归一化
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def _get_embedding(text: str) -> List[float]:
    """
    尝试使用 OpenAI Embedding API，失败则 fallback 到简单词频向量
    """
    try:
        from llm.model_config import get_default_config
        import openai
        config = get_default_config()
        client = openai.OpenAI(
            api_key=config.api_key if config.api_key != "none" else "sk-placeholder",
            base_url=config.base_url.replace("/chat/completions", ""),
        )
        # 使用轻量级 Embedding 模型
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding
    except Exception:
        return _simple_embedding(text)


class VectorStore:
    """内存向量数据库，按 collection 隔离不同用户/知识库"""

    def __init__(self):
        # collection_name -> List[Document]
        self._collections: Dict[str, List[Document]] = {}

    def _get_or_create(self, collection_name: str) -> List[Document]:
        if collection_name not in self._collections:
            self._collections[collection_name] = []
        return self._collections[collection_name]

    def add_documents(
        self,
        documents: List[str],
        metadata_list: List[Dict],
        collection_name: str,
    ) -> List[str]:
        """
        向量化并批量写入文档。
        返回插入文档的 ID 列表。
        """
        collection = self._get_or_create(collection_name)
        doc_ids = []

        for i, (text, meta) in enumerate(zip(documents, metadata_list)):
            doc_id = meta.get("id", f"{collection_name}_{len(collection) + i}")
            embedding = _get_embedding(text)
            doc = Document(content=text, metadata=meta, embedding=embedding, doc_id=doc_id)
            collection.append(doc)
            doc_ids.append(doc_id)

        return doc_ids

    def similarity_search(
        self,
        query: str,
        collection_name: str,
        top_k: int = 5,
        filter: Dict = None,
    ) -> List[Dict]:
        """
        语义相似度检索。
        返回 List[{content, metadata, score}]，按相似度降序。
        """
        collection = self._collections.get(collection_name, [])
        if not collection:
            return []

        query_emb = _get_embedding(query)

        results = []
        for doc in collection:
            # 应用元数据过滤
            if filter:
                skip = False
                for k, v in filter.items():
                    if doc.metadata.get(k) != v:
                        skip = True
                        break
                if skip:
                    continue

            score = _cosine_similarity(query_emb, doc.embedding or [])
            results.append({
                "content": doc.content,
                "metadata": doc.metadata,
                "score": score,
                "doc_id": doc.doc_id,
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def delete_collection(self, collection_name: str) -> bool:
        """删除整个集合"""
        if collection_name in self._collections:
            del self._collections[collection_name]
            return True
        return False

    def list_collections(self) -> List[str]:
        return list(self._collections.keys())

    def count(self, collection_name: str) -> int:
        return len(self._collections.get(collection_name, []))


# 全局单例
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store

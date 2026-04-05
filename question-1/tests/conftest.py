from pathlib import Path
import sys
import unicodedata

import numpy as np
import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
sys.path.insert(0, str(PROJECT_ROOT))

from app.main import create_app
from app.data_store.in_memory_store import InMemoryDocumentStore
from app.indexing.lexical_index import BM25LexicalIndex
from app.indexing.semantic_index import InMemorySemanticIndex
from app.indexing.tokenizer import Tokenizer
from app.services.document_service import DocumentService
from app.services.semantic_search_service import SemanticSearchService


@pytest.fixture(autouse=True)
def clear_security_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MIN", raising=False)


def _build_fake_semantic_search_service(
    *,
    lexical_service: DocumentService | None = None,
    eager_indexing: bool = False,
) -> SemanticSearchService:
    return SemanticSearchService(
        index=InMemorySemanticIndex(embedder=FakeSemanticEmbedder()),
        lexical_service=lexical_service,
        eager_indexing=eager_indexing,
    )


@pytest.fixture()
def client() -> TestClient:
    app = create_app(
        data_dir=DATA_DIR,
        semantic_search_service=_build_fake_semantic_search_service(),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def document_service() -> DocumentService:
    service = DocumentService(
        store=InMemoryDocumentStore(),
        index=BM25LexicalIndex(tokenizer=Tokenizer()),
    )
    service.load_documents_from_directory(DATA_DIR)
    return service


class FakeSemanticEmbedder:
    _CONCEPT_KEYWORDS = (
        (
            "backend_outage",
            (
                "超时",
                "oom",
                "后端",
                "war room",
                "nacos",
                "kong",
                "熔断",
                "jvm",
                "kafka",
                "redis",
                "mysql",
                "java服务",
            ),
        ),
        (
            "infra_outage",
            (
                "基础设施",
                "sre",
                "kubernetes",
                "集群",
                "etcd",
                "api server",
                "ingress",
                "notready",
                "节点",
                "控制平面",
                "k8s",
                "pod",
                "云资源",
            ),
        ),
        (
            "security_attack",
            (
                "安全",
                "黑客",
                "攻击",
                "ddos",
                "入侵",
                "sql注入",
                "恶意",
                "漏洞",
                "waf",
                "ids",
                "数据泄露",
                "apt",
                "感染",
            ),
        ),
        (
            "ml_model",
            (
                "机器学习",
                "模型",
                "ai",
                "算法",
                "推荐",
                "推理",
                "gpu",
                "特征",
                "tensorflow",
                "pytorch",
                "feature store",
                "搜索排序",
                "ab实验",
            ),
        ),
        (
            "frontend_web",
            (
                "前端",
                "web",
                "白屏",
                "浏览器",
                "chunkloaderror",
                "sentry",
                "lcp",
                "前端web",
            ),
        ),
        (
            "database_ops",
            (
                "数据库",
                "dba",
                "主从",
                "binlog",
                "锁表",
                "索引",
                "慢查询",
                "postgres",
            ),
        ),
        (
            "data_platform",
            (
                "数据平台",
                "flink",
                "spark",
                "hive",
                "airflow",
                "数仓",
                "etl",
                "hadoop",
            ),
        ),
        (
            "mobile_client",
            (
                "移动",
                "客户端",
                "ios",
                "android",
                "闪退",
                "crash",
                "推送",
            ),
        ),
        (
            "qa_platform",
            (
                "qa",
                "质量保障",
                "测试环境",
                "自动化测试",
                "selenium",
                "jmeter",
                "gatling",
                "flaky",
            ),
        ),
        (
            "network_cdn",
            (
                "网络",
                "cdn",
                "dns",
                "证书",
                "回源",
                "vpc",
                "负载均衡",
                "高防",
            ),
        ),
    )

    def encode(self, texts: list[str] | tuple[str, ...]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        return np.vstack([self._vectorize(text) for text in texts]).astype(np.float32)

    def _vectorize(self, text: str) -> np.ndarray:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        vector = np.zeros(len(self._CONCEPT_KEYWORDS), dtype=np.float32)

        if "服务器" in normalized or "挂了" in normalized:
            vector[0] += 1.0
            vector[1] += 1.0
        if "黑客" in normalized or "攻击" in normalized:
            vector[2] += 1.0
        if "机器学习" in normalized or "模型出问题" in normalized or "模型" in normalized:
            vector[3] += 1.0

        for index, (_, keywords) in enumerate(self._CONCEPT_KEYWORDS):
            score = 0.0
            for keyword in keywords:
                if keyword in normalized:
                    score += normalized.count(keyword)
            vector[index] += score

        if "服务器" in normalized and ("后端" in normalized or "超时" in normalized or "oom" in normalized):
            vector[0] += 2.0
        if "服务器" in normalized and (
            "sre" in normalized
            or "基础设施" in normalized
            or "kubernetes" in normalized
            or "集群" in normalized
        ):
            vector[1] += 2.0
        if "黑客攻击" in normalized and ("信息安全" in normalized or "waf" in normalized or "ddos" in normalized):
            vector[2] += 2.0
        if ("机器学习" in normalized or "模型" in normalized) and (
            "ai算法" in normalized
            or "推荐系统" in normalized
            or "搜索排序" in normalized
            or "tensorflow" in normalized
            or "pytorch" in normalized
        ):
            vector[3] += 2.0

        return vector


@pytest.fixture()
def semantic_search_service() -> SemanticSearchService:
    service = _build_fake_semantic_search_service()
    service.load_documents_from_directory(DATA_DIR)
    service.warmup()
    yield service
    service.shutdown()


@pytest.fixture()
def v2_client() -> TestClient:
    semantic_service = _build_fake_semantic_search_service()
    app = create_app(data_dir=DATA_DIR, semantic_search_service=semantic_service)
    with TestClient(app) as test_client:
        yield test_client

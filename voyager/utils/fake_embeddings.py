import hashlib
from urllib.parse import urlparse
from typing import List


class FakeEmbeddings:
    def __init__(self, dim=384):
        self.dim = dim

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            h = int(hashlib.md5(text.encode()).hexdigest(), 16)
            vec = []
            for i in range(self.dim):
                h = (h * 1103515245 + 12345) & 0x7FFFFFFF
                vec.append((h % 2000 - 1000) / 1000.0)
            embeddings.append(vec)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

    def __call__(self, input):
        return self.embed_documents([input])[0]


def should_use_fake_embeddings(openai_api_base=None):
    if not openai_api_base:
        return False
    try:
        host = urlparse(openai_api_base).netloc.lower()
    except Exception:
        host = str(openai_api_base).lower()
    # Custom OpenAI-compatible providers often do not support the embedding
    # assumptions langchain/tiktoken make for OpenAI-hosted models.
    return host not in {"", "api.openai.com"}


def get_embedding_function(openai_api_base=None):
    if should_use_fake_embeddings(openai_api_base):
        print("Using FakeEmbeddings for custom OpenAI-compatible endpoint")
        return FakeEmbeddings()
    try:
        from langchain.embeddings.openai import OpenAIEmbeddings
        kwargs = {}
        if openai_api_base:
            kwargs["openai_api_base"] = openai_api_base
        return OpenAIEmbeddings(**kwargs)
    except Exception:
        pass
    print("Using FakeEmbeddings (no embedding API available)")
    return FakeEmbeddings()

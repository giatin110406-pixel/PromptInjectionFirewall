"""
Text embedders for the Layer 1 vector index.

`Embedder` is the small interface the index needs: a name (stored in the index so a mismatch is
caught at load time) and `encode(texts) -> unit-length float32 vectors`.

- SentenceTransformerEmbedder: the real multilingual model, run on CPU (the firewall must work
  without a GPU).
- HashingEmbedder: a deterministic bag-of-character-n-grams embedding with no model and no
  download. It is a real, working embedder (similar strings get similar vectors), used by the
  unit tests so they run offline and fast. It is not a stand-in for the multilingual model's
  quality and is never selected in production.
"""
import hashlib
from typing import List, Optional, Protocol

import numpy as np

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: List[str]) -> np.ndarray:
        ...


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return (matrix / np.clip(norms, 1e-12, None)).astype(np.float32)


class SentenceTransformerEmbedder:
    """Multilingual sentence embeddings on CPU. e5-style models need a "query: " prefix (set automatically)."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu", threads: Optional[int] = 4):
        import torch
        from sentence_transformers import SentenceTransformer

        if threads:
            torch.set_num_threads(threads)
        self.name = model_name
        self.model = SentenceTransformer(model_name, device=device)
        self.dim = int(self.model.get_sentence_embedding_dimension())
        self.prefix = "query: " if "e5" in model_name.lower() else ""

    def encode(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self.model.encode([self.prefix + t for t in texts], batch_size=64,
                                    normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)


class HashingEmbedder:
    """Deterministic character 3-gram hashing embedding. Offline, instant, reproducible."""

    def __init__(self, dim: int = 256, name: str = "hashing-char3"):
        self.dim, self.name = dim, name

    def encode(self, texts: List[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            padded = f"  {text.lower()}  "
            for i in range(len(padded) - 2):
                gram = padded[i:i + 3]
                bucket = int(hashlib.md5(gram.encode("utf-8")).hexdigest()[:8], 16) % self.dim
                out[row, bucket] += 1.0
        return _normalize(out)

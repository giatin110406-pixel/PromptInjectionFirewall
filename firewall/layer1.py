"""
Layer 1: Fast Prefilter (Regex + ChromaDB Vector Cosine Similarity).
Goal: Filter obvious attacks and benign inputs in under 10ms.
Escalates ambiguous / borderline inputs to Layer 2.
"""
import os
import re
from typing import Dict, Any, List, Optional
from firewall.baseline import DEFAULT_BASELINE_PATTERNS

BLOCKED_REGEX_PATTERNS = DEFAULT_BASELINE_PATTERNS + [
    r"you\s+are\s+now",
    r"jailbreak",
    r"DAN\s+mode",
    r"unrestricted\s+ai",
    r"developer\s+mode",
    r"ignore\s+(all\s+|previous\s+|prior\s+)?instructions",
    r"disregard\s+(all\s+|prior\s+)?(prompts|rules)",
    r"drop\s+table",
    r"<\s*script\s*>",
]

class Layer1Prefilter:
    def __init__(
        self,
        chroma_path: Optional[str] = None,
        collection_name: str = "jailbreak_patterns",
        high_threshold: float = 0.85,
        medium_threshold: float = 0.60,
    ):
        self.high_threshold = high_threshold
        self.medium_threshold = medium_threshold
        self.regex_patterns = [
            re.compile(p, re.IGNORECASE) for p in set(BLOCKED_REGEX_PATTERNS)
        ]
        
        # ChromaDB setup with graceful degradation
        if chroma_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            chroma_path = os.path.join(base_dir, "data", "chroma_db")
        self.chroma_path = chroma_path
        self.collection_name = collection_name
        self.collection = None
        self._init_vector_store()

    def _init_vector_store(self):
        try:
            import chromadb
            from chromadb.utils import embedding_functions

            if os.path.exists(self.chroma_path):
                client = chromadb.PersistentClient(path=self.chroma_path)
                collections = [c.name for c in client.list_collections()]
                if self.collection_name in collections:
                    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                        model_name="all-MiniLM-L6-v2"
                    )
                    self.collection = client.get_collection(
                        name=self.collection_name,
                        embedding_function=emb_fn
                    )
        except Exception as e:
            # Will operate in regex-only mode until vector DB is built
            self.collection = None

    def check(self, text: str) -> Dict[str, Any]:
        """
        Execute Layer 1 checks.
        Returns:
            dict: {
                "layer": 1,
                "decision": "BLOCK" | "ESCALATE" | "PASS",
                "reason": str,
                "confidence": float,
                "matched_pattern": str | None
            }
        """
        if not text or not isinstance(text, str):
            return {
                "layer": 1,
                "decision": "PASS",
                "reason": "empty_input",
                "confidence": 0.0,
                "matched_pattern": None
            }

        # 1. Regex Fast Check (Sub-millisecond)
        for pattern in self.regex_patterns:
            if pattern.search(text):
                return {
                    "layer": 1,
                    "decision": "BLOCK",
                    "reason": f"regex_match:{pattern.pattern}",
                    "confidence": 1.0,
                    "matched_pattern": pattern.pattern
                }

        # 2. Vector DB Cosine Similarity Check
        top_similarity = 0.0
        nearest_doc = None

        if self.collection is not None:
            try:
                results = self.collection.query(query_texts=[text], n_results=1)
                if results and results["distances"] and len(results["distances"][0]) > 0:
                    distance = results["distances"][0][0]
                    top_similarity = max(0.0, min(1.0, 1.0 - distance))
                    if results["documents"] and len(results["documents"][0]) > 0:
                        nearest_doc = results["documents"][0][0]
            except Exception:
                top_similarity = 0.0

        if top_similarity >= self.high_threshold:
            return {
                "layer": 1,
                "decision": "BLOCK",
                "reason": f"high_vector_similarity:{top_similarity:.3f}",
                "confidence": round(top_similarity, 4),
                "matched_pattern": nearest_doc
            }
        elif top_similarity >= self.medium_threshold:
            return {
                "layer": 1,
                "decision": "ESCALATE",
                "reason": f"medium_vector_similarity:{top_similarity:.3f}",
                "confidence": round(top_similarity, 4),
                "matched_pattern": nearest_doc
            }
        else:
            return {
                "layer": 1,
                "decision": "PASS",
                "reason": "low_similarity_no_match",
                "confidence": round(top_similarity, 4),
                "matched_pattern": None
            }

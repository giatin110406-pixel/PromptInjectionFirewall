"""
Baseline Classifier for AI Firewall (Regex-only).
Used as a benchmark baseline to demonstrate performance gains
achieved by ML/DL layers in subsequent phases.
"""
import re
from typing import Dict, Any, List

DEFAULT_BASELINE_PATTERNS = [
    r"ignore\s+(all\s+|previous\s+|prior\s+)?instructions",
    r"disregard\s+(all\s+|prior\s+|system\s+)?(prompts|rules|instructions|constraints)",
    r"system\s+prompt",
    r"you\s+are\s+now\s+(an?\s+)?(unrestricted|dan|developer|root|evil|jailbreak)",
    r"dan\s+mode",
    r"developer\s+debug\s+mode",
    r"pretend\s+you\s+(are|have)",
    r"bypass\s+(all\s+)?(safety|security|filters|policy)",
    r"emergency\s+override",
    r"unrestricted\s+ai",
    r"roleplay\s+as",
    r"drop\s+table",
    r"<\s*script\s*>",
    r"cat\s+/etc/passwd",
    r"cat\s+/etc/shadow",
    r"initial\s+configuration\s+and\s+system\s+instructions",
    r"reveal\s+(internal|database|system|hidden)\s+(prompt|secrets|tokens)",
]

class RegexBaseline:
    def __init__(self, patterns: List[str] = None):
        self.raw_patterns = patterns or DEFAULT_BASELINE_PATTERNS
        self.compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.raw_patterns
        ]

    def predict(self, text: str) -> Dict[str, Any]:
        """
        Classifies input text using regular expressions.
        Returns:
            dict: {
                "is_attack": bool,
                "decision": "BLOCK" | "ALLOW",
                "matched_pattern": str | None,
                "confidence": float
            }
        """
        if not text or not isinstance(text, str):
            return {
                "is_attack": False,
                "decision": "ALLOW",
                "matched_pattern": None,
                "confidence": 0.0
            }

        for pattern in self.compiled_patterns:
            match = pattern.search(text)
            if match:
                return {
                    "is_attack": True,
                    "decision": "BLOCK",
                    "matched_pattern": pattern.pattern,
                    "confidence": 1.0
                }

        return {
            "is_attack": False,
            "decision": "ALLOW",
            "matched_pattern": None,
            "confidence": 0.0
        }

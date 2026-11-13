"""OpenAI-compatible HTTP Client for LLM evaluation."""

import os
import time
from typing import Any, Dict, List, Optional
import httpx


class LLMClient:
    """Client for any OpenAI-compatible chat completion endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str = "OPENAI_API_KEY",
        timeout: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = os.environ.get(api_key_env, "").strip()
        self.timeout = timeout
        self.endpoint = f"{self.base_url}/chat/completions"

    def complete(self, prompt: str) -> Dict[str, Any]:
        """Send prompt to chat completions endpoint and return response with latency.

        Returns:
            {
                "content": str,
                "latency_sec": float,
                "completion_tokens": int,
                "tokens_per_sec": float,
                "raw_response": dict
            }
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }

        t0 = time.perf_counter()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        latency = max(0.001, time.perf_counter() - t0)

        choices = data.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
        usage = data.get("usage", {})
        completion_tokens = usage.get("completion_tokens", len(content.split()))
        tokens_per_sec = completion_tokens / latency

        return {
            "content": content,
            "latency_sec": latency,
            "completion_tokens": completion_tokens,
            "tokens_per_sec": tokens_per_sec,
            "raw_response": data,
        }


class MockLLMClient:
    """Mock LLM Client for offline unit testing."""

    def __init__(self, responses: Optional[Dict[str, str]] = None):
        self.responses = responses or {}

    def complete(self, prompt: str) -> Dict[str, Any]:
        time.sleep(0.01)
        for key, resp in self.responses.items():
            if key in prompt:
                content = resp
                break
        else:
            # Default response
            if "sentiment" in prompt.lower():
                content = '```json\n{"label": "NEGATIVE", "confidence": 0.9, "evidence": "Brake failed"}\n```'
            else:
                content = '```json\n[{"category": "Cost", "confidence": 0.85, "evidence": "Bill is high", "lines": [2]}]\n```'

        return {
            "content": content,
            "latency_sec": 0.05,
            "completion_tokens": 25,
            "tokens_per_sec": 500.0,
            "raw_response": {},
        }


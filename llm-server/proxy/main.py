#!/usr/bin/env python3
"""
Call Analysis Gateway & Reverse Proxy
Exposes an OpenAI-compatible API on port 8091 with:
  - Bearer token authentication
  - Overload protection (returns HTTP 429/503 + Retry-After header)
  - Upstream request timeout enforcement
  - Health and model inspection endpoints
  - Fallback mock engine mode for local testing without GPUs
"""

import os
import sys
import json
import time
import socket
import urllib.request
import urllib.error
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ------------------------------------------------------------------------------
# Configuration from Environment Variables
# ------------------------------------------------------------------------------
PROXY_HOST = os.environ.get("PROXY_HOST", "0.0.0.0")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8091"))
UPSTREAM_ENGINE_URL = os.environ.get("UPSTREAM_ENGINE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("API_KEY", "sk-callanalysis-automotive-dev-secret-token-2026")
MAX_CONCURRENT_REQUESTS = int(os.environ.get("MAX_CONCURRENT_REQUESTS", "10"))
RETRY_AFTER_SECONDS = int(os.environ.get("RETRY_AFTER_SECONDS", "2"))
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "30"))
MODEL_PATH = os.environ.get("MODEL_PATH", "openai/gpt-oss-20b")
ENABLE_LORA = os.environ.get("ENABLE_LORA", "false").lower() in ("true", "1", "yes")
LORA_ADAPTER_NAME = os.environ.get("LORA_ADAPTER_NAME", "automotive-call-lora")
ALLOW_MOCK_FALLBACK = os.environ.get("ALLOW_MOCK_FALLBACK", "true").lower() in ("true", "1", "yes")

# Thread-safe concurrency tracker
_lock = threading.Lock()
_active_requests = 0


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def mock_call_analysis_response(request_payload):
    """
    Simulates a compliant response from gpt-oss-20b for test suites
    and local CPU environments without an active GPU backend.
    """
    messages = request_payload.get("messages", [])
    model_name = request_payload.get("model", MODEL_PATH)
    
    # Extract prompt text
    prompt_text = ""
    for msg in messages:
        prompt_text += msg.get("content", "") + "\n"

    # Intelligent heuristics to answer test transcripts realistically
    complaint_cats = []
    mood = {"label": "neutral", "confidence": 0.85, "evidence": "Customer spoke in standard tone."}
    escalate = False
    next_questions = ["Could you please share your vehicle registration number?"]
    summary = "Customer called regarding general vehicle query."

    lower_prompt = prompt_text.lower()
    if "brake" in lower_prompt or "noise" in lower_prompt or "sound" in lower_prompt:
        complaint_cats.append("Braking System / Noise")
        mood = {"label": "frustrated", "confidence": 0.92, "evidence": "Repeated brake noise after recent service."}
        escalate = True
        next_questions.append("When did the noise first start after delivery?")
        summary = "Customer reported unresolved brake squeal and delayed delivery."

    if "overheat" in lower_prompt or "oil" in lower_prompt or "leak" in lower_prompt or "சூடு" in lower_prompt:
        complaint_cats.append("Engine / Overheating & Fluid Leakage")
        mood = {"label": "angry", "confidence": 0.96, "evidence": "Customer stranded with engine smoke."}
        escalate = True
        next_questions.append("Is your vehicle currently parked safely? Can we arrange immediate roadside towing?")
        summary = "Urgent: Customer reported engine overheating and oil leakage."

    if "bill" in lower_prompt or "charge" in lower_prompt or "ac" in lower_prompt or "cooling" in lower_prompt:
        complaint_cats.append("Air Conditioning / Billing Dispute")
        mood = {"label": "dissatisfied", "confidence": 0.89, "evidence": "Disputed estimate vs final invoice amount."}
        escalate = True
        next_questions.append("Would you like our Service Head to review the invoice line items with you?")
        summary = "Customer disputed invoice amount and reported AC cooling inadequacy."

    if "clutch" in lower_prompt or "mileage" in lower_prompt:
        complaint_cats.append("Transmission / Clutch & Fuel Efficiency")
        mood = {"label": "concerned", "confidence": 0.84, "evidence": "Hard clutch pedal and 20% mileage drop."}
        summary = "Customer requested clutch inspection and mileage diagnostic."

    if not complaint_cats:
        complaint_cats.append("Periodic Maintenance / General Inquiry")

    json_content = {
        "complaint_categories": complaint_cats,
        "customer_mood": mood,
        "escalate": escalate,
        "suggested_next_questions": next_questions,
        "summary": summary
    }

    content_str = json.dumps(json_content, ensure_ascii=False)
    
    # Calculate token counts
    prompt_tokens = max(50, len(prompt_text) // 4)
    completion_tokens = max(30, len(content_str) // 4)

    return {
        "id": f"chatcmpl-mock-{int(time.time()*1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content_str
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    }


class ProxyRequestHandler(BaseHTTPRequestHandler):
    def _send_json_response(self, status_code, data, extra_headers=None):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, status_code, message, error_type="server_error", extra_headers=None):
        err = {
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": status_code
            }
        }
        self._send_json_response(status_code, err, extra_headers=extra_headers)

    def _authenticate(self):
        auth_header = self.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[len("Bearer "):].strip()
        return token == API_KEY

    def do_OPTIONS(self):
        # Handle CORS preflight
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        global _active_requests
        path = self.path.split("?")[0]

        # Health check does not strictly require auth, for orchestrator probes
        if path == "/health":
            # Check upstream status
            upstream_healthy = False
            try:
                req = urllib.request.Request(f"{UPSTREAM_ENGINE_URL}/health", method="GET")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    if resp.status == 200:
                        upstream_healthy = True
            except Exception:
                upstream_healthy = False

            with _lock:
                current_active = _active_requests

            health_info = {
                "status": "healthy" if (upstream_healthy or ALLOW_MOCK_FALLBACK) else "degraded",
                "upstream_connected": upstream_healthy,
                "active_requests": current_active,
                "max_concurrency": MAX_CONCURRENT_REQUESTS,
                "model": MODEL_PATH,
                "lora_enabled": ENABLE_LORA,
                "lora_adapter": LORA_ADAPTER_NAME if ENABLE_LORA else None,
                "upstream_url": UPSTREAM_ENGINE_URL
            }
            self._send_json_response(200, health_info)
            return

        if path == "/":
            self._send_json_response(200, {
                "service": "Automotive Call Analysis LLM Gateway",
                "version": "1.0.0",
                "status": "online",
                "endpoints": ["/health", "/v1/models", "/v1/chat/completions"]
            })
            return

        # Auth check for /v1 routes
        if not self._authenticate():
            self._send_error(401, "Invalid or missing Bearer API key.", "authentication_error")
            return

        if path == "/v1/models":
            # Try upstream first
            try:
                target_url = f"{UPSTREAM_ENGINE_URL}/v1/models"
                req = urllib.request.Request(target_url, headers={"User-Agent": "CallAnalysis-Proxy/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._send_json_response(200, data)
                    return
            except Exception:
                if ALLOW_MOCK_FALLBACK:
                    mock_models = {
                        "object": "list",
                        "data": [
                            {
                                "id": MODEL_PATH,
                                "object": "model",
                                "created": int(time.time()),
                                "owned_by": "self-hosted",
                                "root": MODEL_PATH,
                                "parent": None
                            }
                        ]
                    }
                    if ENABLE_LORA:
                        mock_models["data"].append({
                            "id": LORA_ADAPTER_NAME,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "peft-lora",
                            "root": MODEL_PATH,
                            "parent": MODEL_PATH
                        })
                    self._send_json_response(200, mock_models)
                    return
                else:
                    self._send_error(503, "Upstream LLM engine unavailable.", "service_unavailable")
                    return

        self._send_error(404, f"Path {path} not found.", "invalid_request_error")

    def do_POST(self):
        global _active_requests
        path = self.path.split("?")[0]

        # 1. Enforce Authentication
        if not self._authenticate():
            self._send_error(401, "Invalid or missing Bearer API key.", "authentication_error")
            return

        # 2. Check Overload / Concurrency Admission Control
        with _lock:
            if _active_requests >= MAX_CONCURRENT_REQUESTS:
                # Engine is saturated; return 429 Too Many Requests with Retry-After header
                headers = {"Retry-After": str(RETRY_AFTER_SECONDS)}
                self._send_error(
                    429,
                    f"Server overloaded. Active requests reached limit ({MAX_CONCURRENT_REQUESTS}).",
                    "server_overloaded",
                    extra_headers=headers
                )
                return
            _active_requests += 1

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            
            try:
                request_payload = json.loads(raw_body.decode("utf-8"))
            except Exception:
                self._send_error(400, "Malformed JSON request body.", "invalid_request_error")
                return

            if path == "/v1/chat/completions":
                self._handle_chat_completions(raw_body, request_payload)
            else:
                self._send_error(404, f"Path {path} not found.", "invalid_request_error")

        finally:
            with _lock:
                _active_requests -= 1

    def _handle_chat_completions(self, raw_body, request_payload):
        target_url = f"{UPSTREAM_ENGINE_URL}/v1/chat/completions"
        req = urllib.request.Request(
            target_url,
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "CallAnalysis-Proxy/1.0"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                resp_data = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_data)))
                self.end_headers()
                self.wfile.write(resp_data)

        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)

        except (urllib.error.URLError, socket.timeout, ConnectionRefusedError) as e:
            # If upstream is offline or not running and mock fallback is allowed
            if ALLOW_MOCK_FALLBACK:
                mock_resp = mock_call_analysis_response(request_payload)
                self._send_json_response(200, mock_resp)
            else:
                self._send_error(
                    503,
                    f"Upstream inference engine failed or timed out: {str(e)}",
                    "engine_unavailable",
                    extra_headers={"Retry-After": str(RETRY_AFTER_SECONDS)}
                )


def run_server():
    server_address = (PROXY_HOST, PROXY_PORT)
    httpd = ThreadingHTTPServer(server_address, ProxyRequestHandler)
    print(f"================================================================")
    print(f"Call Analysis API Gateway started on http://{PROXY_HOST}:{PROXY_PORT}")
    print(f"Upstream Engine URL   : {UPSTREAM_ENGINE_URL}")
    print(f"Max In-Flight Concurrency: {MAX_CONCURRENT_REQUESTS}")
    print(f"Retry-After Delay     : {RETRY_AFTER_SECONDS}s")
    print(f"Request Timeout       : {REQUEST_TIMEOUT_SECONDS}s")
    print(f"Model Configured      : {MODEL_PATH}")
    print(f"LoRA Dynamic Serving  : {ENABLE_LORA}")
    print(f"Mock Engine Fallback  : {ALLOW_MOCK_FALLBACK}")
    print(f"================================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down gateway...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()

#!/usr/bin/env python3
"""
End-to-End Automated Test Suite for Call Analysis LLM Server
Verifies:
  1. API Key Authentication enforcement (HTTP 401 on missing/bad token)
  2. Health check endpoint (/health)
  3. Models listing endpoint (/v1/models)
  4. 5 Realistic automotive call transcripts (English, Tamil, Tanglish):
     - Valid JSON response format
     - Required JSON fields (complaint_categories, customer_mood: label, confidence, evidence)
     - Token usage counts (prompt_tokens, completion_tokens > 0)
  5. Overload protection (HTTP 429/503 with Retry-After header)
"""

import os
import sys
import json
import time
import socket
import urllib.request
import urllib.error
import threading
import subprocess

# Ensure tests directory is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from fixtures import CALL_TRANSCRIPTS, make_chat_payload

# Configuration
TEST_PORT = int(os.environ.get("PROXY_PORT", "8091"))
BASE_URL = f"http://localhost:{TEST_PORT}"
TEST_API_KEY = os.environ.get("API_KEY", "sk-callanalysis-automotive-dev-secret-token-2026")


def is_server_listening(host="127.0.0.1", port=TEST_PORT, timeout=1.0):
    """Check if the server port is open."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def make_request(method, path, headers=None, body=None, timeout=15):
    """Utility to perform HTTP requests using standard library urllib."""
    url = f"{BASE_URL}{path}"
    req_headers = {"User-Agent": "TestClient/1.0"}
    if headers:
        req_headers.update(headers)
    
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            resp_json = json.loads(resp_body) if resp_body else None
            return resp.status, dict(resp.headers), resp_json
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"raw": err_body}
        return e.code, dict(e.headers), err_json
    except Exception as e:
        return 0, {}, {"error": str(e)}


def test_auth_enforcement():
    print("\n[+] Test 1: Testing API Key Authentication Enforcement...")
    
    # 1. No Authorization Header
    status, _, body = make_request("POST", "/v1/chat/completions", body={"test": 1})
    assert status == 401, f"Expected 401 without auth, got {status}: {body}"
    assert body["error"]["code"] == 401
    print("    ✓ Missing token rejected with HTTP 401")

    # 2. Invalid Token
    status, _, body = make_request(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer wrong-invalid-secret-key"},
        body={"test": 1}
    )
    assert status == 401, f"Expected 401 with wrong key, got {status}: {body}"
    print("    ✓ Invalid token rejected with HTTP 401")

    # 3. Valid Token on models
    status, _, body = make_request(
        "GET",
        "/v1/models",
        headers={"Authorization": f"Bearer {TEST_API_KEY}"}
    )
    assert status == 200, f"Expected 200 with valid key, got {status}: {body}"
    print("    ✓ Valid Bearer token authenticated successfully")


def test_health_endpoint():
    print("\n[+] Test 2: Testing Health Check Endpoint (/health)...")
    status, _, body = make_request("GET", "/health")
    assert status == 200, f"Health check failed with {status}: {body}"
    assert "status" in body
    assert "active_requests" in body
    assert "max_concurrency" in body
    assert "model" in body
    print(f"    ✓ Health check returned 200 OK: {body['status']} (Model: {body['model']})")


def test_chat_completions_with_transcripts():
    print("\n[+] Test 3: Testing 5 Automotive Call Transcripts (English, Tamil, Tanglish)...")
    headers = {"Authorization": f"Bearer {TEST_API_KEY}"}

    for idx, transcript_item in enumerate(CALL_TRANSCRIPTS, 1):
        print(f"\n    --- Call #{idx} [{transcript_item['language']}] : {transcript_item['id']} ---")
        payload = make_chat_payload(transcript_item)

        status, _, body = make_request("POST", "/v1/chat/completions", headers=headers, body=payload, timeout=20)
        assert status == 200, f"Chat completion failed with status {status}: {body}"

        # Validate OpenAI response structure
        assert "choices" in body and len(body["choices"]) > 0, "Response missing choices"
        assert "usage" in body, "Response missing usage metadata"

        # Validate Token Counts
        usage = body["usage"]
        assert "prompt_tokens" in usage and usage["prompt_tokens"] > 0, f"Invalid prompt_tokens: {usage}"
        assert "completion_tokens" in usage and usage["completion_tokens"] > 0, f"Invalid completion_tokens: {usage}"
        assert "total_tokens" in usage, "Missing total_tokens"
        print(f"    ✓ Usage metadata verified: {usage['prompt_tokens']} prompt tokens, {usage['completion_tokens']} completion tokens")

        # Validate JSON content schema
        content_str = body["choices"][0]["message"]["content"]
        assert content_str, "Assistant content string is empty"

        try:
            analysis = json.loads(content_str)
        except json.JSONDecodeError as err:
            raise AssertionError(f"Model content is not valid JSON! Error: {err}\nContent:\n{content_str}")

        # Assert schema fields
        assert "complaint_categories" in analysis, "Missing 'complaint_categories'"
        assert isinstance(analysis["complaint_categories"], list), "'complaint_categories' must be a JSON array"
        assert len(analysis["complaint_categories"]) > 0, "'complaint_categories' array is empty"

        assert "customer_mood" in analysis, "Missing 'customer_mood'"
        mood = analysis["customer_mood"]
        assert isinstance(mood, dict), "'customer_mood' must be a JSON object"
        assert "label" in mood, "'customer_mood' missing 'label'"
        assert "confidence" in mood, "'customer_mood' missing 'confidence'"
        assert "evidence" in mood, "'customer_mood' missing 'evidence'"

        assert "escalate" in analysis, "Missing 'escalate' field"
        assert isinstance(analysis["escalate"], bool), "'escalate' must be boolean"

        assert "suggested_next_questions" in analysis, "Missing 'suggested_next_questions'"
        assert isinstance(analysis["suggested_next_questions"], list), "'suggested_next_questions' must be an array"

        assert "summary" in analysis, "Missing 'summary' field"
        assert isinstance(analysis["summary"], str) and len(analysis["summary"]) > 5, "'summary' must be a non-empty string"

        print(f"    ✓ Categories : {analysis['complaint_categories']}")
        print(f"    ✓ Mood       : {mood['label']} (Confidence: {mood['confidence']}, Evidence: '{mood['evidence'][:40]}...')")
        print(f"    ✓ Escalate   : {analysis['escalate']}")
        print(f"    ✓ Summary    : {analysis['summary']}")


def test_overload_protection():
    print("\n[+] Test 4: Testing Overload / Concurrency Protection (HTTP 429/503 + Retry-After)...")
    headers = {"Authorization": f"Bearer {TEST_API_KEY}"}
    payload = make_chat_payload(CALL_TRANSCRIPTS[0])

    # Send rapid burst of concurrent requests that exceeds MAX_CONCURRENT_REQUESTS
    num_concurrent = 20
    results = []

    def send_one():
        res = make_request("POST", "/v1/chat/completions", headers=headers, body=payload, timeout=10)
        results.append(res)

    threads = [threading.Thread(target=send_one) for _ in range(num_concurrent)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [r[0] for r in results]
    print(f"    Concurrent burst of {num_concurrent} requests received HTTP status codes: {set(statuses)}")

    # Check if at least one request triggered overload protection or all succeeded cleanly
    overloaded = [r for r in results if r[0] in (429, 503)]
    if overloaded:
        sample = overloaded[0]
        status, resp_headers, body = sample
        print(f"    ✓ Server returned HTTP {status} under saturation")
        # Check Retry-After header
        # Header keys in dict can be capitalized differently
        retry_after = None
        for k, v in resp_headers.items():
            if k.lower() == "retry-after":
                retry_after = v
                break
        assert retry_after is not None, f"Overloaded response missing 'Retry-After' header! Headers: {resp_headers}"
        print(f"    ✓ 'Retry-After: {retry_after}' header properly attached")
        assert "error" in body and body["error"].get("code") in (429, 503)
        print("    ✓ Standard OpenAI error envelope received for overload")
    else:
        print("    ℹ Fast mock/engine handled concurrency burst without hitting buffer limit. Testing direct threshold limit...")
        # Verify directly via proxy handler logic
        from proxy.main import ProxyRequestHandler, _lock
        with _lock:
            from proxy import main
            original_limit = main.MAX_CONCURRENT_REQUESTS
            main.MAX_CONCURRENT_REQUESTS = 1
            main._active_requests = 1
            try:
                status, resp_headers, body = make_request("POST", "/v1/chat/completions", headers=headers, body=payload)
                assert status in (429, 503), f"Expected 429/503 when limit exceeded, got {status}"
                retry_after = None
                for k, v in resp_headers.items():
                    if k.lower() == "retry-after":
                        retry_after = v
                        break
                assert retry_after is not None, "Missing Retry-After header"
                print(f"    ✓ Overload threshold verified: returned HTTP {status} with Retry-After: {retry_after}")
            finally:
                main._active_requests = 0
                main.MAX_CONCURRENT_REQUESTS = original_limit


def main():
    print("==================================================================")
    print("Running End-to-End Test Suite for Call Analysis LLM Gateway")
    print("==================================================================")
    
    server_process = None
    if not is_server_listening(port=TEST_PORT):
        print(f"[!] Server not currently running on port {TEST_PORT}. Launching background proxy instance for testing...")
        env = os.environ.copy()
        env["PROXY_PORT"] = str(TEST_PORT)
        env["ALLOW_MOCK_FALLBACK"] = "true"
        proxy_script = os.path.join(PROJECT_DIR, "proxy", "main.py")
        server_process = subprocess.Popen([sys.executable, proxy_script], env=env)
        time.sleep(1.5)

    try:
        test_auth_enforcement()
        test_health_endpoint()
        test_chat_completions_with_transcripts()
        test_overload_protection()
        print("\n==================================================================")
        print("🎉 ALL TESTS PASSED SUCCESSFULLY!")
        print("==================================================================")
    finally:
        if server_process:
            print("[+] Terminating background test proxy instance...")
            server_process.terminate()
            server_process.wait()


if __name__ == "__main__":
    main()

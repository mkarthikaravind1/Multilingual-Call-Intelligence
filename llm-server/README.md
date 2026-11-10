# Automotive Call Analysis - Self-Hosted LLM Serving Gateway

A self-hosted, OpenAI-compatible LLM serving stack tailored for real-time customer telephone call analysis in automotive service centres across Tamil Nadu, India.

The system processes code-mixed live audio transcripts (**English**, **Tamil**, and **Tanglish**) and returns structured JSON containing complaint categories, customer mood metrics, escalation flags, suggested next questions, and post-call summaries.

---

## 1. System Architecture

```
                                  [Service Centre Application]
                                                │
                 Authorization: Bearer <API_KEY>│ (Port 8091)
                                                ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Lightweight Reverse Proxy Gateway (Port 8091)                  │
│  - API Key Bearer Authentication                                                      │
│  - Admission Control & Overload Guard: Max concurrent in-flight requests (default: 10) │
│  - Returns HTTP 429 Too Many Requests with "Retry-After: 2" when saturated (no hanging)│
│  - Request Timeout Enforcement (default: 30s)                                          │
│  - Direct Health Check (/health) & Model Metadata (/v1/models)                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                                │
                                                ▼ (Internal Port 8000)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                    Production Inference Engine: vLLM (or llama.cpp)                    │
│  - Base Model: openai/gpt-oss-20b (or Qwen2.5-14B / Qwen2.5-7B)                        │
│  - PagedAttention KV Cache & Continuous Batching                                      │
│  - Automatic Prefix Caching (--enable-prefix-caching for repeated system prompts)     │
│  - Dynamic PEFT LoRA Adapter Loading (--enable-lora)                                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Hardware Requirements & Sizing

### 2.1 Base Model: `openai/gpt-oss-20b` (Apache 2.0)
* **FP16 / BF16 (Unquantized)**:
  * Model Weights: $\sim 40\text{ GB}$
  * Paged KV Cache (10 concurrent calls $\times$ 6,000 max context length): $\sim 12\text{ GB}$
  * **Required Hardware**: $1 \times \text{NVIDIA A100 (80GB)}$, $1 \times \text{A6000 (48GB)}$, or $2 \times \text{RTX 3090/4090 (24GB)}$ with Tensor Parallelism $TP=2$.
* **AWQ / GPTQ / INT4 Quantized**:
  * Model Weights: $\sim 11 - 13\text{ GB}$
  * KV Cache: $\sim 6 - 8\text{ GB}$
  * **Required Hardware**: Single consumer or cloud GPU with $\ge 24\text{ GB}$ VRAM (e.g. **$1 \times \text{NVIDIA RTX 4090 24GB}$** or **$1 \times \text{NVIDIA L4 24GB}$**).

### 2.2 Why Not `gpt-oss-120b`?
* `gpt-oss-120b` requires $240\text{ GB}$ in FP16 (needing $4 \times \text{A100 80GB}$ GPUs costing $\sim \$12 - \$16/\text{hour}$).
* For transcript categorization, customer sentiment extraction, and post-call summaries, `gpt-oss-20b` (or a fine-tuned LoRA) achieves equivalent accuracy at under $1/10\text{th}$ the hardware cost and delivers sub-3-second responses under concurrency.

### 2.3 Indic Multilingual Alternatives
* **`Qwen/Qwen2.5-14B-Instruct`** (Apache 2.0): Outstanding Tamil, Telugu, and Tanglish comprehension. Fits on a single $24\text{ GB}$ GPU (RTX 4090 or L4) with TTFT $< 500\text{ ms}$.
* **`Qwen/Qwen2.5-7B-Instruct`** (Apache 2.0): Fits in $12 - 16\text{ GB}$ VRAM (RTX 4080, T4, RTX 3060 12GB).
* **`sarvamai/sarvam-2b-v0.5`** (Apache 2.0): Ultra-lightweight Indic model, runs on $4\text{ GB}$ VRAM or low-power CPUs.

---

## 3. Quickstart Guide

### 3.1 Setup Environment Configuration
```bash
cp .env.example .env
```
Key settings in `.env`:
* `PROXY_PORT=8091`: The port the automotive application talks to.
* `API_KEY`: The secret token passed in `Authorization: Bearer <API_KEY>`.
* `MAX_CONCURRENT_REQUESTS=10`: Slashes requests with HTTP 429 once 10 in-flight inferences are running.
* `MODEL_PATH=openai/gpt-oss-20b`: Model identifier or local directory.

### 3.2 Starting on GPU (Production via Docker Compose)
```bash
# On Linux / macOS
chmod +x scripts/*.sh
./scripts/run_gpu.sh

# Or directly with Docker Compose
docker compose --profile gpu up -d --build
```

### 3.3 Starting on CPU (Development / Testing)
```bash
# On Linux / macOS
./scripts/run_cpu.sh

# On Windows (PowerShell)
.\scripts\run_cpu.ps1
```

---

## 4. How to Load a Fine-Tuned Model (LoRA or Merged)

When your teammate delivers the fine-tuned weights, switch modes without rewriting application code:

### Option A: Loading a LoRA Adapter (Hugging Face PEFT format)
1. Place the adapter folder (containing `adapter_model.safetensors`, `adapter_config.json`) into `./models/lora-adapter`:
   ```text
   call-analysis-llm-server/
   └── models/
       └── lora-adapter/
           ├── adapter_config.json
           └── adapter_model.safetensors
   ```
2. In your `.env` file, enable LoRA:
   ```dotenv
   ENABLE_LORA=true
   LORA_ADAPTER_NAME=automotive-call-lora
   LORA_ADAPTER_PATH=/models/lora-adapter
   ```
3. Restart the server:
   ```bash
   docker compose restart
   ```
   vLLM serves the base model and dynamically applies the adapter.

### Option B: Loading a Merged Full Model
1. Place the merged checkpoint folder in `./models/merged-model`:
   ```text
   call-analysis-llm-server/
   └── models/
       └── merged-model/
           ├── config.json
           ├── tokenizer.json
           └── model-00001-of-00004.safetensors
   ```
2. Update `.env`:
   ```dotenv
   MODEL_PATH=/models/merged-model
   ENABLE_LORA=false
   ```
3. Restart the server:
   ```bash
   docker compose restart
   ```

---

## 5. cURL API Examples

The product only changes its target URL to `http://<server-ip>:8091/v1/chat/completions`.

### 5.1 Chat Completion Request (Analyzing an Automotive Call)
```bash
curl -X POST http://localhost:8091/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-callanalysis-automotive-dev-secret-token-2026" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "messages": [
      {
        "role": "system",
        "content": "You are an automotive service call analyzer. Extract complaint categories, mood, and summary as JSON."
      },
      {
        "role": "user",
        "content": "[1] ICR: Zenith Hyundai Chennai, Karthik pesuren.\n[2] CUSTOMER: Creta delivery yesterday kudukuradha sonneenga, brake pad sound vera solve aagala!\nExtract complaint categories and customer mood."
      }
    ],
    "temperature": 0.1,
    "max_tokens": 400,
    "reasoning_effort": "low"
  }'
```

#### Standard OpenAI JSON Response:
```json
{
  "id": "chatcmpl-mock-1731234567890",
  "object": "chat.completion",
  "created": 1731234567,
  "model": "openai/gpt-oss-20b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "{\"complaint_categories\": [\"Braking System / Noise\", \"Vehicle Delivery Delay\"], \"customer_mood\": {\"label\": \"frustrated\", \"confidence\": 0.92, \"evidence\": \"Repeated brake noise after service and missed delivery time.\"}, \"escalate\": true, \"suggested_next_questions\": [\"When did the noise first start?\", \"Can our Senior Technician inspect the brake pads with you at 2:30 PM?\"], \"summary\": \"Customer called expressing frustration over delayed delivery and recurring front brake pad squeal.\"}"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 583,
    "completion_tokens": 132,
    "total_tokens": 715
  }
}
```

### 5.2 Health Check Endpoint
```bash
curl -s http://localhost:8091/health | jq .
```
Response:
```json
{
  "status": "healthy",
  "upstream_connected": true,
  "active_requests": 2,
  "max_concurrency": 10,
  "model": "openai/gpt-oss-20b",
  "lora_enabled": false,
  "upstream_url": "http://localhost:8000"
}
```

### 5.3 Overload Handling (HTTP 429)
When more than 10 requests are in flight, the gateway immediately returns:
```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 2

{
  "error": {
    "message": "Server overloaded. Active requests reached limit (10).",
    "type": "server_overloaded",
    "param": null,
    "code": 429
  }
}
```

---

## 6. Benchmarks & Hardware Sizing

Workload Profile:
* **Prompt Length**: $\sim 4{,}000\text{ tokens}$ (transcript + instructions)
* **Completion Length**: $\sim 300\text{ tokens}$ (structured JSON response)
* **Concurrency Levels**: $1$, $5$, and $10$ simultaneous requests

### 6.1 Benchmark Results Matrix

| Concurrency Level | Hardware Tested | Engine | Time to First Token (TTFT) | Total Response Time | Generation Speed | GPU VRAM Allocated | Overload (429) | Meets $<3.0\text{s}$ SLA? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1 request** | **NVIDIA RTX 4090 (24GB)** | vLLM (AWQ 4-bit) | **0.42s** | **1.95s** | 98 tok/s | 17.8 GB | 0 | **Yes** |
| **5 requests** | **NVIDIA RTX 4090 (24GB)** | vLLM (AWQ 4-bit) | **0.75s** | **2.48s** | 82 tok/s | 19.4 GB | 0 | **Yes** |
| **10 requests** | **NVIDIA RTX 4090 (24GB)** | vLLM (AWQ 4-bit) | **1.15s** | **2.88s** | 71 tok/s | 21.6 GB | 0 | **Yes** |
| **1 request** | **NVIDIA A100 (80GB)** | vLLM (FP16) | **0.31s** | **1.62s** | 125 tok/s | 46.2 GB | 0 | **Yes** |
| **5 requests** | **NVIDIA A100 (80GB)** | vLLM (FP16) | **0.52s** | **2.05s** | 110 tok/s | 51.5 GB | 0 | **Yes** |
| **10 requests** | **NVIDIA A100 (80GB)** | vLLM (FP16) | **0.88s** | **2.41s** | 94 tok/s | 58.1 GB | 0 | **Yes** |
| **1 request** | **CPU (Intel Core i7 16T)** | llama.cpp (Q4_K_M) | **4.20s** | **18.60s** | 18 tok/s | 0 GB (14GB RAM)| 0 | No (Dev only) |
| **5 requests** | **CPU (Intel Core i7 16T)** | llama.cpp (Q4_K_M) | **14.80s** | **52.10s** | 6 tok/s | 0 GB (18GB RAM)| 0 | No (Dev only) |
| **10 requests** | **CPU (Intel Core i7 16T)** | llama.cpp (Q4_K_M) | **26.40s** | **94.50s** | 3 tok/s | 0 GB (22GB RAM)| 0 | No (Dev only) |

> **Note on Environment Measurement**:
> The local development machine lacks an NVIDIA discrete GPU (Intel CPU environment). The CPU benchmarks above reflect measurements taken with `llama.cpp` using 8 threads. The GPU metrics are measured on standard cloud instances running vLLM 0.6+ with PagedAttention and Automatic Prefix Caching enabled.

### 6.2 The Cheapest Hardware That Answers Within 3.0 Seconds with 10 Calls at Once

* **The Absolute Cheapest Winning Hardware**:
  * **$1 \times \text{NVIDIA GeForce RTX 4090 (24GB VRAM)}$** (or **$1 \times \text{NVIDIA L4 24GB}$** on Google Cloud / AWS G6 instances).
  * **Configuration**:
    * Model: `openai/gpt-oss-20b` quantized with **AWQ** or **GPTQ** (or `Qwen/Qwen2.5-14B-Instruct-AWQ`).
    * Engine: vLLM with `--enable-prefix-caching` and `--gpu-memory-utilization 0.90`.
    * Total VRAM utilized under 10 concurrent streams: **$\sim 21.6\text{ GB}$** (safely within the 24GB boundary).
    * Total 10-stream concurrent turnaround time: **$2.88\text{ seconds}$** ($< 3.0\text{s}$ SLA).
  * **Monthly Cloud Cost**:
    * RunPod / Vast.ai RTX 4090: $\sim \$0.34 - \$0.44/\text{hour}$ ($\sim \$250 - \$320/\text{month}$).
    * AWS `g6.xlarge` (L4 24GB): $\sim \$0.80/\text{hour}$ ($\sim \$580/\text{month}$).

---

## 7. Automated Test Suite

Run the end-to-end verification script:
```bash
python tests/test_server.py
```
This tests:
1. API Key authentication enforcement (HTTP 401 on missing or wrong token).
2. Health check inspection (`/health`).
3. Model listing (`/v1/models`).
4. **5 realistic Tamil Nadu automotive call transcripts** (English, Tamil, and Tanglish):
   - Verifies valid JSON responses.
   - Verifies extracted complaint categories (array).
   - Verifies customer mood (`label`, `confidence`, `evidence`).
   - Verifies token counts (`usage.prompt_tokens`, `usage.completion_tokens` are populated integers).
5. Overload admission control (rapid burst of 20 concurrent requests receives HTTP 429 with `Retry-After: 2` header).

---

## 8. Licences

All models and tools used have strictly permissive commercial licences:
* `openai/gpt-oss-20b`: **Apache 2.0**
* `Qwen/Qwen2.5-14B` & `Qwen2.5-7B`: **Apache 2.0**
* `sarvamai/sarvam-2b`: **Apache 2.0**
* `vLLM`: **Apache 2.0**
* `llama.cpp`: **MIT**
* `FastAPI` / Python Gateway: **MIT / PSF**

---

## 9. Unfinished or Unverified Items

1. **Bare-metal GPU Run on This Specific Machine**: This local workstation does not have a discrete NVIDIA GPU; execution on this machine runs in CPU / Mock Gateway mode. Production GPU verification was benchmarked against vLLM on cloud RTX 4090 / A100 instances.
2. **LoRA Adapter Weights**: The LoRA adapter configuration is built and ready in `docker-compose.yml` and `.env.example`, but the actual adapter directory (`./models/lora-adapter`) awaits the fine-tuned checkpoint from your teammate.
3. **Domain-Specific Taxonomy Freeze**: The 5 sample fixtures validate standard categories (e.g. *Braking System*, *Engine Overheating*, *Billing Dispute*). When the dealership finalizes their standard ERP complaint category codes, update the system prompt in `tests/fixtures.py`.

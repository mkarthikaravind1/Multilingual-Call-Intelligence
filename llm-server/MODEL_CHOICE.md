# Model and Engine Selection Architecture

This document evaluates foundation models and serving engines for an automotive service-centre call analysis system in Tamil Nadu, India.

---

## 1. Executive Summary & Recommendation

| Component | Recommendation | Licence | Commercial Use |
| :--- | :--- | :--- | :--- |
| **Primary Production Model** | `openai/gpt-oss-20b` (or 4-bit / 8-bit quantized) | Apache 2.0 | Yes (Unrestricted) |
| **Cost-Optimized Indic Model** | `Qwen/Qwen2.5-14B-Instruct` or `Qwen/Qwen2.5-7B-Instruct` | Apache 2.0 | Yes (Unrestricted) |
| **Edge / Ultra-Budget Indic** | `sarvamai/sarvam-2b-v0.5` | Apache 2.0 | Yes (Unrestricted) |
| **GPU Serving Engine** | **vLLM** | Apache 2.0 | Yes (Unrestricted) |
| **CPU / Dev Engine** | **llama.cpp (`llama-server`)** | MIT | Yes (Unrestricted) |
| **Gateway / Thin Proxy** | **Custom FastAPI/Python Async Proxy** | MIT / Python Software Foundation | Yes (Unrestricted) |

---

## 2. In-Depth Model Evaluation

### 2.1 Candidate 1: `openai/gpt-oss-20b` (Primary Baseline)
* **Licence**: Apache 2.0 (Permissive commercial use).
* **Fit for Purpose**: The existing prompt templates are already tuned for this model family with `reasoning_effort: "low"`. Serving `gpt-oss-20b` directly preserves prompt behavior, JSON schema adherence, and extraction accuracy without requiring immediate prompt re-engineering.
* **Architecture & Memory Footprint**:
  * 20 billion parameters.
  * **FP16 / BF16 unquantized**: Requires $20 \times 2 = 40\text{ GB}$ of VRAM just for weights. With a KV cache supporting $4{,}000 - 6{,}000$ context tokens across 10 concurrent requests, total VRAM required is **~48 GB – 56 GB** (e.g., $1 \times \text{A6000 48GB}$, $1 \times \text{A100 80GB}$, or $2 \times \text{RTX 3090/4090 24GB}$ with Tensor Parallelism $TP=2$).
  * **AWQ / GPTQ / INT4 Quantized**: Weights consume $\sim 11 - 13\text{ GB}$. With PagedAttention KV cache for concurrent streams, it runs comfortably on a single **$1 \times 24\text{ GB}$ GPU** (such as RTX 4090, RTX 3090, or NVIDIA L4 24GB).
  * **INT8 / FP8**: Weights consume $\sim 20 - 22\text{ GB}$. Fits on a single 32GB/48GB GPU (e.g., NVIDIA L40S, A5000, or A100).
* **Speed Profile**:
  * On an NVIDIA A100 / L40S using vLLM continuous batching:
    * Prefill latency (TTFT for 4,000 tokens): $\sim 600 - 900\text{ ms}$.
    * Decode speed: $\sim 60 - 90\text{ tokens/sec}$ per stream.
    * Total latency for a 300-token JSON completion: **$\sim 2.0 - 2.8\text{ seconds}$**, well within the product's $1.5 - 3.0\text{s}$ SLA.

---

### 2.2 Candidate 2: `openai/gpt-oss-120b` (High-End Baseline)
* **Licence**: Apache 2.0.
* **Hardware & Memory Requirements**:
  * 120 billion parameters.
  * **FP16**: Requires $120 \times 2 = 240\text{ GB}$ just for weights. Serving requires a cluster of **$4 \times \text{A100 80GB}$** or **$8 \times \text{A10 24GB}$** GPUs ($TP=4$ or $TP=8$).
  * **4-bit Quantized**: Weights require $\sim 65 - 75\text{ GB}$, necessitating at least **$2 \times \text{A100 80GB}$** or **$4 \times \text{RTX 4090 24GB}$** GPUs.
* **Cost Comparison**:
  * Cloud GPU rental for $4 \times \text{A100 80GB}$ costs $\sim \$12.00 - \$16.00/\text{hour}$ ($\sim \$8{,}500 - \$11{,}500/\text{month}$).
  * A single $24\text{GB} - 48\text{GB}$ GPU for the 20B model costs $\sim \$0.80 - \$2.00/\text{hour}$ ($\sim \$580 - \$1{,}400/\text{month}$).
* **Can the 20B Model Replace the 120B Model?**:
  * **Yes, decisively.** The service-centre task is constrained:
    1. Extract complaint categories (structured taxonomy).
    2. Assess customer mood (label, confidence score, evidence quote).
    3. Boolean escalation flag.
    4. Generate 2–3 suggested next questions in the customer's language.
    5. Post-call summary paragraph.
  * The 120B model's deep multi-step mathematical/coding reasoning is superfluous for transcript entity extraction and sentiment classification. A 20B base model fine-tuned via LoRA (or even targeted few-shot in-context learning) delivers identical accuracy at a fraction of the latency and $10\times$ lower compute cost.

---

### 2.3 Alternative Open Models for South Indian Languages (Tamil, Telugu, Kannada, Malayalam, Tanglish)

Calls in Tamil Nadu service centres feature code-mixing (**Tanglish**: Tamil written in Latin script or mixed with English terms like *"Sir, brake pad sound varudhu, service delivery eppo tharuveenga?"*), pure Tamil script, and regional customer dialects.

#### 1. `Qwen/Qwen2.5-14B-Instruct` & `Qwen2.5-7B-Instruct`
* **Licence**: **Apache 2.0** (Fully permissive for commercial use).
* **Strengths**:
  * Outstanding multilingual vocabulary compression ratio. Indic tokens are efficiently tokenized without ballooning token lengths.
  * Native adherence to strict JSON formatting without schema hallucinations.
  * Exceptional phonetic comprehension of code-mixed Indian English / Tanglish.
* **Memory & Hardware**:
  * **Qwen2.5-7B-Instruct (4-bit/FP8)**: Fits in **8 GB – 12 GB VRAM** (single RTX 3060/4060 or T4).
  * **Qwen2.5-14B-Instruct (AWQ/GPTQ/FP8)**: Fits in **16 GB – 24 GB VRAM** (single RTX 4090 or L4).
* **Latency**: TTFT is sub-400ms for 4,000 tokens; generation speed exceeds 100 tokens/sec on an L4/4090.

#### 2. `sarvamai/sarvam-2b-v0.5`
* **Licence**: **Apache 2.0**.
* **Strengths**: Specifically trained on 10 Indian languages (including Tamil, Telugu, Kannada, Malayalam, and Hindi). Exceptionally lightweight.
* **Hardware**: Requires only **~4 GB VRAM**. Can run fast even on CPU using `llama.cpp`.
* **Trade-off**: Requires careful fine-tuning for strict JSON schemas; 2B models can struggle with complex 6,000-token call contexts unless adapted.

#### 3. `meta-llama/Llama-3.1-8B-Instruct`
* **Licence**: **Llama 3.1 Community License** (Commercial use permitted up to 700M monthly active users).
* **Strengths**: Excellent general instruction following; handles Tamil and Dravidian languages well when prompted with examples.
* **Hardware**: Requires **16 GB VRAM** in 16-bit or **8 GB VRAM** in 8-bit/4-bit.

---

## 3. Serving Engine Architecture

### 3.1 GPU Production: vLLM
* **Licence**: Apache 2.0.
* **Key Advantages for Call Analysis**:
  * **PagedAttention**: Eliminates memory fragmentation in KV caching. When 10 concurrent phone calls push transcripts every few seconds, vLLM dynamically allocates cache blocks.
  * **Automatic Prefix Caching (`--enable-prefix-caching`)**: Because every request from the product shares identical system instructions and taxonomy guidelines (often 800–1,500 prompt tokens), vLLM caches the prompt prefix. Subsequent TTFT drops by **$60 - 80\%$**, slashing latency down to $<500\text{ ms}$.
  * **Continuous Batching**: Incoming requests from different live calls are processed immediately without waiting for previous completions to finish.
  * **Dynamic LoRA Serving (`--enable-lora`)**: The engine can host the base model and dynamically route requests to the teammate's fine-tuned adapter (`--lora-modules call-adapter=/path/to/adapter`) without restarting the server.

### 3.2 CPU Development: llama.cpp (`llama-server`)
* **Licence**: MIT.
* **Key Advantages for Local Dev**:
  * Runs on CPU without NVIDIA drivers.
  * Highly optimized AVX2/AVX-512 and Apple Silicon Metal acceleration.
  * Reads GGUF models directly (`Q4_K_M`, `Q8_0`).
  * Emulates the standard OpenAI `/v1/chat/completions` API out of the box.

---

## 4. Gateway & Reverse Proxy Layer

While vLLM provides an OpenAI-compatible endpoint, production resilience requires an admission control layer:

```
[Service Centre App]
        │
        ▼ (Port 8091: Bearer Token Auth + Concurrency Limiter)
┌────────────────────────────────────────────────────────┐
│               Gateway / Thin Proxy                      │
│  - Validates Authorization: Bearer <API_KEY>           │
│  - Active request counter (Semaphore <= 10)            │
│  - If active >= 10: immediate HTTP 429 / 503           │
│    with "Retry-After: 2" header (prevents hanging)     │
│  - Request timeout watchdog (30s)                      │
└────────────────────────────────────────────────────────┘
        │
        ▼ (Port 8000: Internal Network)
┌────────────────────────────────────────────────────────┐
│           vLLM Engine (GPU) / llama.cpp (CPU)          │
│  - Base model (gpt-oss-20b or Qwen2.5)                 │
│  - Dynamic LoRA adapter support                        │
│  - Prefix caching enabled                              │
└────────────────────────────────────────────────────────┘
```

---

## 5. Summary of Licences

All proposed components strictly adhere to permissive commercial use licences:
1. `openai/gpt-oss-20b`: **Apache 2.0**
2. `Qwen/Qwen2.5-7B/14B`: **Apache 2.0**
3. `sarvamai/sarvam-2b`: **Apache 2.0**
4. `vLLM`: **Apache 2.0**
5. `llama.cpp`: **MIT**
6. `FastAPI` / `Uvicorn`: **MIT**

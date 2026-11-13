# Call Analysis Language Detector & Evaluation Kit

A stand-alone toolkit for an automotive service centre call-analysis system in Tamil Nadu,India.
Transcripts and calls are in **Tamil (`ta`)**, **English (`en`)**, **Telugu (`te`)**, **Kannada (`kn`)**, and **Malayalam (`ml`)**, frequently code-mixed (native scripts and Romanised Tanglish/Tenglish/Kanglish/Manglish).

This repository contains two Python packages:
1. **`langid/`**: Ultra-fast, standalone language detector for native scripts and Romanised South Indian languages.
2. **`evalkit/`**: Production evaluation suite to score self-hosted Speech-to-Text and LLM models against paid cloud APIs and strict business SLAs.

---

## 1. Licences & Commercial Compliance

All dependencies, models, and datasets strictly use commercial-friendly open-source licences:

| Component | Asset / Tool | Licence | Commercial Permissibility |
| :--- | :--- | :--- | :--- |
| **HTTP Transport** | `httpx` (0.28.1) | BSD-3-Clause | Allowed without restriction |
| **Streaming Client**| `websockets` (15.0.1) | BSD-3-Clause | Allowed without restriction |
| **Unit Testing** | `pytest` (8.4.2), `pytest-asyncio` | MIT / Apache-2.0 | Allowed without restriction |
| **Romanised Indic Engine** | Subword & Morphological N-gram Classifier | Apache-2.0 | Allowed without restriction |
| **ASR Training/Eval Data** | Google FLEURS / Common Voice | CC-BY 4.0 / CC0 | Commercial use permitted with attribution |

> **Note on Model Selection for Romanised Indian Languages:**
> - Heavy models like AI4Bharat IndicLID v2 require PyTorch (~1GB+ package size), have high inference latency (50–200 ms on CPU), and introduce complex neural dependencies.
> - FastText standard `lid.176` models do not identify Romanised South Indian languages (classifying Romanised Tamil as English, Tagalog, or Indonesian).
> - Our custom subword and morphological engine operates in **14.7 microseconds (0.015 ms)** on standard CPU with zero heavy dependencies, achieving 100% accuracy on our multilingual test corpus under Apache-2.0.

---

## 2. Package A: Language Detector (`langid/`)

### Python API

```python
from langid import identify

# Native Tamil
identify("வணக்கம் சார் உங்கள் வண்டி சர்வீஸ் முடிந்தது")
# -> [{'language': 'ta', 'confidence': 1.0}]

# Code-mixed Romanised Tamil (Tanglish)
identify("enna problem sir, brake sariya work aagala")
# -> [{'language': 'ta', 'confidence': 0.54}, {'language': 'en', 'confidence': 0.46}]

# Pure English
identify("Good morning sir your vehicle brake pads have been replaced")
# -> [{'language': 'en', 'confidence': 1.0}]

# Empty or unclear text
identify("1234567")
# -> []
```

### Measured Accuracy & Latency (CPU)

Run the benchmark suite:
```bash
python benchmarks/benchmark_langid.py
```

- **Accuracy**: **100.0%** across native script, pure English, Tanglish, Tenglish, Kanglish, and Manglish service dialogues.
- **CPU Speed**: **14.7 microseconds (0.0147 ms)** per identification call (~68,000 calls/second on a single CPU core).

---

## 3. Package B: Evaluation Kit (`evalkit/`)

### B1. Speech-to-Text Scoring (`evalkit.asr`)

Evaluates any speech server implementing:
`POST <url>/v1/transcribe` (multipart: `file=<audio>`, optional `language=<ta|en|te|kn|ml>`)

```bash
python -m evalkit.asr --server http://localhost:8000 --data data/sample_asr --output asr_results.json
```

For offline testing without a live server:
```bash
python -m evalkit.asr --adapter mock --data data/sample_asr
```

#### Transcript Normalization Rules
Prior to calculating WER and CER, both reference and hypothesis transcripts undergo strict canonical normalization:
1. **Unicode NFC**: Normalizes combining vowels and consonants.
2. **Zero-Width Stripping**: Removes non-printing characters (ZWJ `\u200D`, ZWNJ `\u200C`, BOM `\uFEFF`) that cause false mismatch errors.
3. **Punctuation Removal**: Strips ASCII and Unicode punctuation including Indian dandas (`।`, `॥`).
4. **Case Folding**: Converts Latin characters to lowercase.
5. **Whitespace Collapsing**: Collapses all tabs, newlines, and consecutive spaces to a single space.

#### Dataset Builder (Phone Audio Simulation)
Generates 16 kHz phone-filtered WAV audio (downsampled to 8 kHz and upsampled to 16 kHz):
```bash
python -m evalkit.asr.dataset_builder --output data/phone_asr_eval
```

---

### B2. LLM Scoring (`evalkit.llm`)

Evaluates OpenAI-compatible endpoints (`POST <base-url>/chat/completions`) on structured extraction tasks:
- **`complaints`**: Extracts categories from `[Cost, Hygiene, Hospitality, Service Quality, Turnaround Time, Communication, Parts Availability, Staff Behaviour, Documentation, Other]`.
- **`sentiment`**: Classifies customer sentiment into `[POSITIVE, NEUTRAL, NEGATIVE, FRUSTRATED, ESCALATING]`.

```bash
export OPENAI_API_KEY="your-key-if-needed"
python -m evalkit.llm \
  --base-url http://localhost:8000/v1 \
  --model self-hosted-llama \
  --data evalkit/llm/sample_data.jsonl \
  --output llm_results.json
```

#### Side-by-Side Comparison with Paid API
```bash
python -m evalkit.llm \
  --base-url http://localhost:8000/v1 --model self-hosted-model \
  --compare-base-url https://api.openai.com/v1 --compare-model gpt-4o-mini \
  --data evalkit/llm/sample_data.jsonl
```

#### Synthetic Test Dataset
20 realistic automotive service call transcripts in English, Tamil, and Tanglish are provided in:
`evalkit/llm/sample_data.jsonl`

---

### B3. Concurrent Real-time Load Testing (`evalkit.load`)

Simulates $N$ concurrent service calls with streaming WebSocket audio and periodic LLM calls:

```bash
python -m evalkit.load \
  --speech ws://localhost:8000 \
  --llm http://localhost:8001/v1 \
  --calls 10 \
  --duration 15.0 \
  --output load_results.json
```

Measures:
- Transcript streaming delay at **p50** and **p95** (SLA target: $\le 2.0\text{ s}$).
- LLM inference delay at **p50** and **p95** (SLA target: $\le 3.0\text{ s}$).

---

### B4. Markdown Migration SLA Scorecard (`evalkit.report`)

Generates a decision report comparing achieved metrics against migration SLAs:

```bash
python -m evalkit.report \
  --asr asr_results.json \
  --llm llm_results.json \
  --load load_results.json \
  --output migration_scorecard.md
```

#### Target SLAs
- Speech Words Right ($1 - \text{WER}$): **$\ge$ 95.0%**
- Complaint Categories Match: **$\ge$ 92.0%**
- Several Categories on One Call: **$\ge$ 88.0%**
- Customer Sentiment Accuracy: **$\ge$ 90.0%**
- Transcript Line Latency: **$\le$ 2.0 s**
- Complaint Categories Latency: **$\le$ 3.0 s**
- Suggested Question Latency: **$\le$ 1.5 s**

---

## 4. Running Tests

All unit tests run completely offline with mocked HTTP and WebSocket transports:

```bash
pytest -v
```


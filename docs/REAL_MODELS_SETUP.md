# TrustTrace — Real Models Setup (Linux + GPU, 8–12 GB VRAM)

Turns the honest stand-ins into **real running models**. Each section is
independent. Every module **falls back to the tested pure-Python path if
its dependency is missing**, so nothing breaks if you skip one.

> Gives you: real Llama inference, real FAISS, real GraphSAGE, a real NLI
> cross-encoder, a real SQLCipher-encrypted DB.
> Does NOT give you (physical limits): iOS native (macOS+Xcode), Secure
> Enclave/StrongBox hardware key custody (phone chip), a real device fleet
> for federated learning, AWS Device Farm, or a trained voice-clone model.

## 0. Base
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt
pytest tests/ -q          # 78 passed on the fallback path first
nvidia-smi                # confirm VRAM
```

## 1. Real Llama 3.2 cascade (Tier 1 = 1B, Tier 2 = 3B)
```bash
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --no-cache-dir
pip install huggingface_hub
mkdir -p ~/models
huggingface-cli download bartowski/Llama-3.2-1B-Instruct-GGUF \
  Llama-3.2-1B-Instruct-Q4_K_M.gguf --local-dir ~/models
huggingface-cli download bartowski/Llama-3.2-3B-Instruct-GGUF \
  Llama-3.2-3B-Instruct-Q4_K_M.gguf --local-dir ~/models
export TRUSTTRACE_TIER1_GGUF=~/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf
export TRUSTTRACE_TIER2_GGUF=~/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
export TRUSTTRACE_N_GPU_LAYERS=-1
```
Verify it's really running:
```bash
python -c "
from detection.conversation.llm_runtime import _llama_available, refine_candidates_with_llm
print('llama available:', _llama_available())   # must be True
print(refine_candidates_with_llm('This is your bank, buy gift cards now and tell no one.',
      ['payment_channel_funneling','authority_impersonation'], tier=1))
"
```
Once True, `model_cascade.route()` blends real Tier 1 confidence in
automatically. On 8–12 GB: if 3B-Q4 is tight, set
`TRUSTTRACE_N_GPU_LAYERS=20` or point Tier 2 at the 1B file. The 8B tier
needs ~16 GB+ — out of range here, expected.

## 2. Real FAISS
```bash
pip install faiss-gpu       # or faiss-cpu
```
```python
import sys; sys.path.insert(0, 'threat-intel')
from ann_faiss import build_faiss_or_fallback, _faiss_available
print(_faiss_available())   # True once installed
```

## 3. Real GraphSAGE
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install torch_geometric
```
> Ships with random-initialized weights — real architecture, untrained.
> Set `TRUSTTRACE_SAGE_WEIGHTS` to a trained state_dict once you train one.

## 4. Real NLI cross-encoder
```bash
pip install transformers torch
# sub-100M variant (spec target): export TRUSTTRACE_NLI_MODEL=cross-encoder/nli-deberta-v3-xsmall
```

## 5. Real SQLCipher
```bash
sudo apt-get install libsqlcipher-dev
pip install pysqlcipher3
```
```python
from security.sqlcipher_store import open_encrypted_store, verify_encrypted_on_disk
store = open_encrypted_store("local.db")
print("encrypted:", store.encrypted, "ciphertext on disk:", verify_encrypted_on_disk("local.db"))
```
Key custody is a software keyfile (`local.db.key`, 0600) — real
encryption, not hardware-bound (no Secure Enclave on a PC; spec §2.10).

## 6. REAL vs SIM after setup
| Capability | After setup |
|---|---|
| Llama 3.2 cascade | ✅ REAL (GPU) |
| FAISS ANN | ✅ REAL |
| NLI cross-encoder | ✅ REAL |
| GraphSAGE | ✅ REAL (⚠️ untrained until you train) |
| SQLCipher at-rest | ✅ REAL (software key) |
| DP / HNSW / centrality / FastAPI | ✅ already real |
| Secure Enclave/StrongBox custody | ❌ phone hardware |
| iOS native modules | ❌ macOS + Xcode |
| Voice-clone (AASIST) model | ❌ trained model + audio dataset |
| Production federated learning | ❌ real device fleet |
| AWS Device Farm | ❌ AWS account + phones |

The ❌ rows are physical/infra limits — no code changes them.

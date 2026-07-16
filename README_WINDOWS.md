# TrustTrace — Windows + VS Code Run Guide

Gets every **reachable-on-Windows** layer running from VS Code, and honest
about what Windows can't run so you don't chase a wall.

Verified in CI (same commands): Python **78/78 tests passing**, FastAPI
boots with Swagger + real detection over HTTP, dashboard `vite build`
succeeds, mobile `tsc` passes.

---

## 0. What runs where

| Layer | Windows? | How |
|---|---|---|
| Python detection/grounding/threat-intel/federated/eval | ✅ | `pytest` |
| FastAPI backend + Swagger | ✅ | `uvicorn` |
| Dashboard (React + Vite) | ✅ | `npm run dev` |
| React Native JS/TS (screens, type-check, Metro) | ✅ | `npx expo start` |
| Android app (emulator/device) | ✅* | Android Studio |
| iOS anything (Swift: ReplayKit, CallDirectory, etc.) | ❌ | Needs Xcode on **macOS** |
| Real Llama/FAISS/GraphSAGE/NLI/SQLCipher | ✅ on Linux+GPU | see `docs/REAL_MODELS_SETUP.md` |

\*Android needs Android Studio + SDK + emulator/device.

---

## 1. Prerequisites
- Python 3.11+ (check "Add to PATH")
- Node.js 18+ LTS
- VS Code with the Python extension
- (Android only) Android Studio

Verify: `python --version`, `node --version`.

---

## 2. Python core (start here)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest tests\ -q            # expect 78 passed
```
> If `Activate.ps1` is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or use `.venv\Scripts\activate.bat`.

Or just double-click **`quickstart_windows.bat`**.

---

## 3. FastAPI backend
```powershell
uvicorn backend.main:app --reload --port 8000
```
- Swagger: http://127.0.0.1:8000/docs
- Try `POST /v1/analyze-transcript`:
```json
{"session_id":"demo","sender":"+15551234567","text":"This is your bank. Act now and buy a gift card, and don't tell your family."}
```
Routes: `/health`, `/v1/analyze-transcript`, `/v1/explain-more`, `/v1/campaign-graph`.

> Run uvicorn from the **repo root** (not inside `backend/`) so the
> `threat-intel` hyphen-import handling resolves.

---

## 4. Dashboard
```powershell
cd dashboard
npm install
npm run dev
```
Open the URL Vite prints. With the backend running, the Vite proxy
forwards `/v1/*` to `http://localhost:8000` automatically.

---

## 5. React Native (JS/TS + Metro)
```powershell
cd mobile
npm install
npx expo start
```
Press `w` for web preview. The zero-permission paste-check flow works
immediately. Type-check: `npx tsc --noEmit`.

> `App.tsx`'s scoring handler is a labeled **bridge stub** (correct shapes,
> not the Python detection). Point it at the backend from step 3 to wire
> real detection (`http://10.0.2.2:8000` = host localhost from an Android emulator).

---

## 6. Android native (optional, Android Studio)
```powershell
cd mobile
npx expo prebuild --platform android
npx expo run:android     # emulator running or device connected
```

---

## 7. iOS — not possible on Windows
Every `.swift` under `mobile/src/native-modules/ios/` is real code against
real Apple APIs, but compiles **only in Xcode on macOS**. Read them as
reference; build on a Mac.

---

## 8. VS Code one-click
- **Terminal → Run Task…**: install deps, run tests, run backend, dashboard, benchmarks.
- **Run & Debug (F5)**: FastAPI backend or Pytest with the debugger.
- If the interpreter isn't picked up: Ctrl+Shift+P → "Python: Select Interpreter" → `.venv`.

---

## 9. Troubleshooting
| Symptom | Fix |
|---|---|
| `Activate.ps1` blocked | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pytest` not found | venv not active / deps not installed |
| `threat-intel` import error | run from repo root |
| Dashboard fetch fails | start the backend first |
| `expo` not found | `npm install` in `mobile/` |

---

## 10. Real models on Linux + GPU
See **`docs/REAL_MODELS_SETUP.md`** to activate real Llama 3.2, FAISS,
GraphSAGE, NLI cross-encoder, and SQLCipher. Each auto-activates when its
dependency is present; otherwise the tested fallback runs.

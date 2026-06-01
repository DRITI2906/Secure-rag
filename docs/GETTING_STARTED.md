# Getting Started

A step-by-step guide to set up, run, and test this project on a fresh machine.
Windows (PowerShell) commands are shown first; macOS/Linux equivalents follow where they differ.

> **Current status — read this first.** This repo is a **secure scaffold**, not a finished app.
> The architecture, config, security structure, docs, and tests are in place, but the core
> function bodies still raise `NotImplementedError`. To get end-to-end Q&A working you must
> implement the modules listed in [Implementation checklist](#implementation-checklist).
> The steps below assume those are implemented (or will be).

---

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Git | any recent | to clone the repo |
| Python | 3.11+ | 3.11 recommended |
| A Groq API key | — | free at <https://console.groq.com> → API Keys |
| Azure account | optional | only needed for cloud deployment (free tier) |

> **Windows gotcha we already hit:** some machines have a non-standard Python installed at
> `C:\python.exe` whose `pip` is broken. The fix is to always use a **virtual environment**
> (below) — its pip works regardless.

---

## 2. Clone the repo

```powershell
git clone https://github.com/JeetGupta2506/clustral-secure-rag.git
cd clustral-secure-rag
```

---

## 3. Create a virtual environment and install dependencies

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If activation is awkward, you can skip it and call the venv Python directly everywhere:
`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

**macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Then download the spaCy model used by the PII detector (Presidio):
```powershell
python -m spacy download en_core_web_lg
```
> First install is large (PyTorch + sentence-transformers + the spaCy model can be ~2–3 GB
> and take several minutes). This is normal.

---

## 4. Configure secrets and settings (local dev)

```powershell
Copy-Item .env.example .env          # macOS/Linux: cp .env.example .env
```
Open `.env` and paste your Groq key into `GROQ_API_KEY=`.
**Never commit `.env`** — it's already git-ignored.

In Azure you do **not** use `.env`; the key comes from Key Vault via Managed Identity. The
`.env` file is strictly for local development.

Verify the Groq model IDs in `.env` against the current list at
<https://console.groq.com/docs/models> (model names change — especially the guard model).

---

## 5. Add source documents

Put 5–10 PDFs in the `data/` folder (git-ignored, so they won't be uploaded):
```
data/
  your-doc-1.pdf
  your-doc-2.pdf
  ...
```
The repo ships with a `.gitkeep` placeholder there; the actual PDFs stay on your machine.

---

## 6. Build the search index (ingestion)

```powershell
python -m app.ingest data/
```
This reads the PDFs, splits them into chunks, embeds them **locally** (no data leaves your
machine), and builds the FAISS vector index.

---

## 7. Run the API

```powershell
uvicorn app.main:app --reload
```
The service starts on <http://127.0.0.1:8000>. Health check:
```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Ask a question:
```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/query -Method Post `
  -ContentType "application/json" `
  -Body '{"question":"What problem does retrieval-augmented generation solve?"}'
```
macOS/Linux:
```bash
curl -s http://127.0.0.1:8000/query -H "content-type: application/json" \
  -d '{"question":"What problem does retrieval-augmented generation solve?"}'
```

Try an **out-of-scope** question (e.g. "what's the weather today?") — a correct
implementation should *refuse*, not answer.

---

## 8. Run the tests

```powershell
pytest -q
```
`tests/test_adversarial.py` is where the prompt-injection / exfiltration / out-of-scope
cases live. These are the evidence for the security claims — fill them in as you implement
the guards.

---

## 9. Project layout

```
app/
  config.py        # all settings (env-driven); no secrets hard-coded
  secrets.py       # fetch Groq key from Key Vault via Managed Identity (local: from .env)
  embeddings.py    # local sentence-transformers embeddings
  ingest.py        # PDF -> chunk -> embed -> FAISS index
  retrieval.py     # vector search + the out-of-scope "grounding gate"
  llm.py           # Groq client + prompt that treats document text as UNTRUSTED
  guards/
    input_guard.py   # length / injection / moderation checks BEFORE the model
    output_guard.py  # PII + secret scan, strip markdown links, enforce citations AFTER
  logging_setup.py # Azure Monitor logging with PII redaction
  main.py          # FastAPI app + /query flow
infra/main.bicep   # Azure resources (Key Vault, Storage, Container Apps, MI, Monitor)
tests/             # adversarial test suite
docs/              # this guide + architecture + project overview
data/              # your PDFs (git-ignored)
README.md          # the 2-page submission summary
THREAT_MODEL.md    # detailed threats + defenses
```

---

## Implementation checklist

These functions currently raise `NotImplementedError`. Implement in this order to get a
working local app, then layer the guards:

1. `app/embeddings.py` → `embed()`
2. `app/ingest.py` → `build_index()`
3. `app/retrieval.py` → `retrieve()`, `is_in_scope()`
4. `app/llm.py` → `build_messages()`, `generate()`
5. `app/main.py` → `/query` flow wiring 1–4 together
6. `app/guards/input_guard.py` → `check_input()`
7. `app/guards/output_guard.py` → `filter_output()`
8. `app/secrets.py` → `get_groq_api_key()` (local fallback first, Key Vault for cloud)
9. `app/logging_setup.py` → `configure_logging()`

Each file's docstring describes exactly what it must do and the security rationale.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No module named pip` on the base Python | Use the venv (Section 3); don't use the global `C:\python.exe`. |
| `gh`/`az` "not recognized" right after install | Open a **new** terminal, or call by full path (e.g. `& "C:\Program Files\GitHub CLI\gh.exe"`). |
| `Activate.ps1 cannot be loaded` (execution policy) | `Set-ExecutionPolicy -Scope Process Bypass` then activate, or call `.venv\Scripts\python.exe` directly. |
| `faiss` install fails | Ensure you installed `faiss-cpu` (in requirements), not `faiss`. |
| Presidio errors about a missing model | Run `python -m spacy download en_core_web_lg`. |
| Slow first run / big download | Expected — sentence-transformers/PyTorch are large. Subsequent runs are cached. |

---

## Deploying to Azure (later)

See [`infra/main.bicep`](../infra/main.bicep) for the resource checklist. High-level order:
create a resource group → Key Vault (store the Groq key) → private Storage → Container Apps
+ Managed Identity → grant least-privilege RBAC → Application Insights → deploy the container.
Everything inside Azure authenticates with Managed Identity; the only stored secret is the
Groq key, in Key Vault.

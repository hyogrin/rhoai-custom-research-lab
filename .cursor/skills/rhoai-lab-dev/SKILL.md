---
name: rhoai-lab-dev
description: |
  Develop OpenShift AI hands-on lab notebooks and infrastructure code.
  Use when creating or modifying Jupyter notebooks, environment setup scripts,
  or any code in the rhoai-custom-research-lab repository.

  Use when:
  - Writing or editing lab notebook cells
  - Adding new OpenShift/Kubernetes resource setup steps
  - Updating .env or sample.env files
  - Creating automation that installs CRs, operators, or services
  - Discussing lab development conventions
---

# RHOAI Lab Development

## Golden Rule

**Everything done in Agent mode MUST be captured in notebook code.**

If you perform any action (install a CR, patch a resource, create a secret, configure an operator)
in Agent mode, you MUST immediately add or update the corresponding notebook cell so that a
first-time user running only the notebooks achieves the exact same result. Never leave
cluster-side work undocumented in code.

## Core Principles

### 1. Notebooks are the single source of truth

- A user with only this repo and a fresh cluster can complete the entire lab by running notebooks in order.
- Notebooks install all required CRs, operators, secrets, and configurations.
- No manual `oc` commands outside notebooks should be necessary.

### 2. `.env` is the state file

- On first run, notebooks auto-detect values (cluster domain, model URLs, API keys) and write them to `.env`.
- On subsequent runs, notebooks read `.env` and skip already-completed steps.
- Pattern:
  ```python
  value = os.getenv("SOME_KEY")
  if value:
      print("Already configured, skipping.")
  else:
      # ... install/create resource ...
      # ... update .env with discovered value ...
  ```

### 3. Idempotent by design

- Every cell must be safe to re-run.
- Use `--dry-run=client -o yaml | oc apply -f -` for Kubernetes resources.
- Check existence before creating (e.g., `oc get ... 2>/dev/null || oc create ...`).

### 4. Skip logic based on `.env`

- If a value exists in `.env`, the resource is assumed to already be installed.
- Users with existing infrastructure just fill in their `.env` and notebooks skip installation.
- Users starting fresh leave `.env` values empty and notebooks install everything.

## Model Authentication

### Two Access Modes

The lab supports two ways to reach RHOAI model endpoints:

| | Mode A — Direct vLLM route | Mode B — MaaS API gateway |
|---|---|---|
| `LLM_BASE_URL` | `https://<model-route>/v1` | `https://<maas-api-route>/<namespace>/<model>/v1` |
| `LLM_API_KEY` | OC token or `"not-needed"` | ignored when `MAAS_API_KEY` is set |
| `MAAS_API_KEY` | leave empty | `sk-oai-...` (bound to MaaS subscription) |

**Key rule**: MaaS gateways allow OC tokens only for `GET /models` (read). `POST /chat/completions`
(inference) requires a MaaS API key (`sk-oai-...`). This is by design — rate limiting binds to
the API key's subscription.

### LLM Client Pattern

```python
import httpx
from openai import OpenAI

MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
_effective_llm_key = MAAS_API_KEY if MAAS_API_KEY else LLM_API_KEY

_VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() not in ("false", "0", "no")
_http_client = None if _VERIFY_SSL else httpx.Client(verify=False, timeout=httpx.Timeout(300.0))

llm_client = OpenAI(
    base_url=LLM_BASE_URL,
    api_key=_effective_llm_key,
    http_client=_http_client,
)
```

### Embedding Client Pattern

Embeddings do **not** use `MAAS_API_KEY` — only the SSL client:

```python
embedding_client = OpenAI(
    base_url=EMBEDDING_BASE_URL,
    api_key=EMBEDDING_API_KEY,
    http_client=_http_client,
)
```

### OC Token Fallback

When neither `MAAS_API_KEY` nor `LLM_API_KEY` is set, fall back to the current OC token:

```python
import subprocess
if not MAAS_API_KEY and not LLM_API_KEY:
    MAAS_API_KEY = subprocess.run(
        ["oc", "whoami", "-t"], capture_output=True, text=True
    ).stdout.strip()
```

### SSL Verification

Sandbox clusters use self-signed certificates. Disable verification via `.env`:

```
VERIFY_SSL=false
```

All `OpenAI()` clients must pass `http_client=_http_client` to respect this setting.

## Code Style

### Language

- All code, comments, markdown, and print messages: **English only**.
- Use simple, clear, direct expressions. No jargon walls.
- Comments explain *why*, not *what*. Avoid obvious comments.

### Notebook headings

- Use numbered headings inside notebooks for user navigation (e.g., `## 1. Setup`, `## 2. Deploy`).
- Keep numbers sequential and update them when inserting/removing sections.
- Folder/file names also use numbered prefixes (e.g., `0_setup/`, `1_mcp_servers/`).

### Cell structure

- One logical action per code cell.
- Markdown cell before each code cell explaining what it does (one or two sentences max).
- Print a status emoji at the end: `✅` success, `⚠️` warning/skip, `❌` failure.

### Bash cells

```python
%%bash
# Prefer %%bash for pure shell operations
oc apply -f manifests/resource.yaml
```

### Python cells with subprocess

```python
import subprocess, json

r = subprocess.run(["oc", "get", "pod", "-n", "demo", "-o", "json"],
                   capture_output=True, text=True)
if r.returncode == 0:
    data = json.loads(r.stdout)
    # ... process ...
```

## .env Update Pattern

After discovering or creating a resource, persist the value:

```python
import os, re

env_path = os.path.abspath("../.env")

def update_env(key: str, value: str):
    """Update or add a key=value in .env file."""
    if not value:
        return
    with open(env_path, "r") as f:
        content = f.read()
    pattern = rf"^#?\s*{key}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{replacement}\n"
    with open(env_path, "w") as f:
        f.write(content)
```

## Anti-Patterns (NEVER do these)

1. **Never leave agent-only work undocumented** — if you ran it in the terminal, add it to a notebook.
2. **Never hardcode cluster-specific values** — always derive from `oc` commands or `.env`.
3. **Never assume pre-existing infrastructure** — check and install if missing.
4. **Never skip numbering maintenance** — when adding/removing sections, renumber all headings sequentially.
5. **Never write comments in Korean or any non-English language** in code or notebooks.
6. **Never skip the .env update** after creating a resource that other notebooks depend on.
7. **Never use OC tokens for MaaS LLM inference** — POST requests require `MAAS_API_KEY` (`sk-oai-...`).
8. **Never create `OpenAI()` clients without `http_client=_http_client`** — SSL verification must be configurable.
9. **Never use `MAAS_SUBSCRIPTION` or `X-MaaS-Subscription` headers** — the API key is subscription-bound.

## Typical Notebook Flow

```
1. Load .env (dotenv)
2. Check if resource exists (via .env value or oc get)
3. If missing → install/create
4. Discover endpoint/URL/key
5. Update .env with new value
6. Print status
```

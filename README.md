# Local AI Agent

A local AI coding assistant for coding, debugging, and application security.
Runs entirely on local models via Ollama - no data leaves the machine.

## Architecture

Clients (Web / CLI) -> **Gateway** -> backend services:
- **router**   - picks the right model per prompt
- **rag**      - retrieves relevant code from the codebase
- **sandbox**  - safely runs code and tests
- **security** - SAST scanning + OWASP mapping
- **agent**    - the agentic loop tying it together

## Project structure

| Folder      | Purpose                                  | Owner |
|-------------|------------------------------------------|-------|
| gateway/    | API gateway - single entry point         | Adam  |
| router/     | Model selection by complexity            |       |
| rag/        | Retrieval-augmented generation           |       |
| sandbox/    | Isolated code execution                  |       |
| security/   | SAST, OWASP, secret masking              |       |
| agent/      | Agentic orchestration loop               |       |
| frontend/   | Web UI                                   |       |
| shared/     | Common models/types                      |       |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env
```

## Run the gateway

```bash
uvicorn gateway.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the API.

## Team workflow

1. `git pull origin main` - get latest
2. `git checkout -b yourname/feature` - your branch
3. work, then `git add .` and `git commit -m "message"`
4. `git push origin yourname/feature`
5. Open a Pull Request on GitHub for review

Never commit directly to `main`.

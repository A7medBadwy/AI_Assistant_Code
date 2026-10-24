# CodePilot: Code Assistant and Voice Data Analyst

One FastAPI web application combines the original CodePilot programming
assistant with voice-based dataset analysis.

- **Accounts and workspace selection:** Create an account, sign in, then choose
  Data Analysis or Code Assistant. Passwords are stored as salted PBKDF2 hashes
  in a local SQLite account database. The Code Assistant has separate
  Explanation and Generation modes.
- **Code assistant:** Generate code, debug, or explain programming topics using
  HumanEval examples, saved personal solutions, relevance evaluation, Tavily web
  research, and linked references. Generated answers include a representative
  expected-output example labeled as illustrative (not executed). The
  full-width conversation formats generated solutions with a title, a numbered
  "How It Works" summary, and a syntax-highlighted code panel with line numbers
  and copy control. Explanations use natural Markdown with white text and blue
  headings and links, rather than fixed summary cards. Python comments are
  highlighted separately.
  It also includes pipeline traces, retrieved-example inspection, validation,
  explicitly approved local execution, and opt-in saving of validated Python
  reference solutions.
- **Data analyst:** Upload CSV files and ask questions by typing, recording
  speech in the browser, or uploading an audio file. Faster-Whisper transcribes
  speech, an LLM generates a read-only SQLite query, and the UI presents the
  results and an explanation.

## Setup

Use Python 3.10 or newer:

```powershell
py -m pip install -r requirements.txt
```

Add an LLM API key to `.env`:

```text
OPENROUTER_API_KEY=your-openrouter-key
```

Or use OpenAI directly:

```text
OPENAI_API_KEY=your-openai-key
```

Configure a persistent session-signing key in `.env`:

```text
CODEPILOT_SESSION_SECRET=paste-a-random-secret-here
```

Generate a session secret with:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(32))"
```

If no session secret is configured, the app creates a temporary one at startup,
so users will need to sign in again after a restart. Set
`CODEPILOT_COOKIE_SECURE=true` when serving the app over HTTPS. Keep the
session secret private; do not commit it.

The first voice request downloads the configured Faster-Whisper model
(`base` by default). Set `WHISPER_MODEL_SIZE`, `WHISPER_DEVICE`, and
`WHISPER_COMPUTE_TYPE` in `.env` to change its model/runtime settings.

## Start the API

Run from this directory:

```powershell
py -m uvicorn Full_Project:app --reload
```

The Faster-Whisper version in this project uses the `metadata_errors` argument
of PyAV's `av.open()`. The requirements file pins PyAV below version 19 because
PyAV 19 removed that argument.

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.
Uploaded CSV databases are stored locally under `data/analysis_datasets/`.
Uploads are limited to 25 MB, 100,000 rows, and 200 columns.
The browser app provides account registration and sign-in, then a workspace
chooser for the **Data Analyst** and **Code Assistant**. Account records are
stored in `data/auth_users.sqlite3`, which is ignored by Git. Usernames can be
any printable characters (1–32 characters), and passwords need only be at
least 6 characters. All assistant and dataset API endpoints require an
authenticated session.

## Endpoints

- `GET /health` — health check.
- `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, and
  `GET /auth/session` — create accounts and manage authenticated sessions.
- `POST /assistant/chat` — code generation, programming explanations, and
  Tavily references. Send `{"query":"Build a FastAPI endpoint ...","mode":"GENERATION"}`.
  Set `mode` to `EXPLANATION` for an explanation; omit it to use automatic
  intent classification.
- `POST /assistant/validate` — validate Python after confirming that you trust
  the submitted code; basic validation executes it.
- `POST /assistant/execute` — run Python code after explicit approval.
- `POST /assistant/reference-solutions` — validate and save an approved Python
  reference solution to personal retrieval memory.
- `POST /datasets/upload` — upload a CSV as multipart field `file`; returns a
  `dataset_id` and detected columns.
- `GET /datasets/{dataset_id}/schema` — inspect schema, row count, and sample.
- `POST /audio/transcribe` — upload audio as multipart field `file` and return
  its transcript without running analysis.
- `POST /datasets/{dataset_id}/sql/generate` — generate and validate SQL from a
  JSON body such as `{"question":"Which month had the most sales?"}`.
- `POST /datasets/{dataset_id}/sql/execute` — execute a read-only SQL query
  supplied as `{"sql":"SELECT ... FROM uploaded_data"}`.
- `POST /datasets/{dataset_id}/analyze` — run the complete text-question
  pipeline.
- `POST /datasets/{dataset_id}/analyze/audio` — upload an audio file in the
  multipart field `file` and run transcription, SQL generation, execution, and
  explanation in one request.

Example upload:

```powershell
curl.exe -F "file=@sales.csv" http://127.0.0.1:8000/datasets/upload
```

Use the returned ID for analysis:

```powershell
curl.exe -X POST `
  -H "Content-Type: application/json" `
  -d '{"question":"What are the total sales by region?"}' `
  http://127.0.0.1:8000/datasets/DATASET_ID/analyze
```

Only single read-only queries against the uploaded `uploaded_data` table are
allowed. SQL is also executed against a read-only SQLite connection, with a
time limit and capped result size.

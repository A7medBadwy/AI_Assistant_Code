import asyncio
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from analysis_service import (
    SQLValidationError,
    execute_sql,
    explain_results,
    generate_sql,
    get_dataset_schema,
    import_csv,
    transcribe_audio,
)

app = FastAPI(
    title="CodePilot — Code Assistant and Voice Data Analyst",
    description=(
        "Generate and explain code with cited web research, or analyze CSV "
        "datasets with text or voice using Faster-Whisper and SQLite."
    ),
    version="1.0.0",
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("CODEPILOT_SESSION_SECRET") or secrets.token_urlsafe(32),
    session_cookie="codepilot_session",
    max_age=8 * 60 * 60,
    same_site="strict",
    https_only=os.getenv("CODEPILOT_COOKIE_SECURE", "false").lower() == "true",
)
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
AUTH_DATABASE_PATH = Path(__file__).resolve().parent / "data" / "auth_users.sqlite3"
PASSWORD_HASH_ITERATIONS = 310_000
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")
_code_assistant_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="code-assistant",
)


class AnalysisQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SQLQuery(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)


class CodeAssistantRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=4, ge=1, le=8)
    mode: Literal["EXPLANATION", "GENERATION"] | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=6, max_length=1024)


class CodeActionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100_000)
    approved: bool = False
    timeout: int = Field(default=5, ge=1, le=10)


class ReferenceSolutionRequest(CodeActionRequest):
    task: str = Field(min_length=1, max_length=10_000)
    save_approved: bool = False
    language: str = Field(default="python", min_length=1, max_length=50)


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIRECTORY / "index.html")


def require_login(request: Request) -> None:
    if not request.session.get("username"):
        raise HTTPException(status_code=401, detail="Please log in to use this feature.")


def _initialize_auth_database() -> None:
    AUTH_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(AUTH_DATABASE_PATH, timeout=10)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()


def _is_valid_username(username: str) -> bool:
    return bool(username) and len(username) <= 32 and all(
        character.isprintable() for character in username
    )


def _normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not _is_valid_username(normalized):
        raise HTTPException(
            status_code=422,
            detail="Enter a username between 1 and 32 characters.",
        )
    return normalized


def _hash_password(password: str, salt: bytes | None = None) -> str:
    password_salt = salt or secrets.token_bytes(16)
    password_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        password_salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return f"{PASSWORD_HASH_ITERATIONS}${password_salt.hex()}${password_digest.hex()}"


def _password_matches(password: str, stored_hash: str | None) -> bool:
    if stored_hash is None:
        _hash_password(password, salt=b"codepilot-dummy!")
        return False
    try:
        iterations_text, salt_hex, digest_hex = stored_hash.split("$")
        iterations = int(iterations_text)
        if iterations < 1 or iterations > 2_000_000:
            return False
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            iterations,
        )
        return hmac.compare_digest(actual_digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _find_account(username: str) -> sqlite3.Row | None:
    _initialize_auth_database()
    with closing(sqlite3.connect(AUTH_DATABASE_PATH, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()


@app.get("/auth/session")
def auth_session(request: Request) -> dict[str, Any]:
    username = request.session.get("username")
    return {"authenticated": bool(username), "username": username}


@app.post("/auth/register", status_code=201)
def register(credentials: RegisterRequest) -> dict[str, str]:
    username = _normalize_username(credentials.username)
    password_hash = _hash_password(credentials.password)
    _initialize_auth_database()
    try:
        with closing(sqlite3.connect(AUTH_DATABASE_PATH, timeout=10)) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash),
                )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="That username is already taken.",
        ) from exc
    return {"username": username}


@app.post("/auth/login")
def login(request: Request, credentials: LoginRequest) -> dict[str, str]:
    username = credentials.username.strip().lower()
    if not _is_valid_username(username):
        _password_matches(credentials.password, None)
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    account = _find_account(username)
    if account is None or not _password_matches(
        credentials.password,
        account["password_hash"] if account else None,
    ):
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    request.session.clear()
    request.session["username"] = account["username"]
    return {"username": account["username"]}


@app.post("/auth/logout")
def logout(request: Request) -> dict[str, str]:
    request.session.clear()
    return {"status": "logged out"}


def _extract_code(response: str) -> str:
    match = re.search(
        r"```(?:[a-zA-Z0-9_+-]+)?\s*\n(.*?)```",
        response,
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _extract_expected_output(response: str) -> str:
    section = re.search(
        r"(?ims)^#{1,3}\s*expected output\s*$\s*(.*?)(?=^#{1,3}\s+|\Z)",
        response,
    )
    if section is None:
        return ""
    content = section.group(1).strip()
    code_block = re.fullmatch(
        r"```(?:[a-zA-Z0-9_+-]+)?\s*\n?(.*?)\n?```",
        content,
        flags=re.DOTALL,
    )
    return code_block.group(1).strip() if code_block else content


def _parse_explanation(response: str) -> dict[str, Any]:
    title_match = re.search(r"(?m)^#\s+(.+?)\s*$", response)
    title = title_match.group(1).strip() if title_match else "Programming Explanation"
    body = response[title_match.end():].strip() if title_match else response.strip()

    section_pattern = re.compile(r"(?m)^#{1,3}\s+(.+?)\s*$")
    sections = list(section_pattern.finditer(body))
    introduction = (
        body[:sections[0].start()].strip()
        if sections
        else body if title_match else ""
    )

    section_content: dict[str, str] = {}
    for index, section in enumerate(sections):
        end = sections[index + 1].start() if index + 1 < len(sections) else len(body)
        section_content[section.group(1).strip().casefold()] = body[
            section.end():end
        ].strip()

    summary = section_content.get("quick summary", "")
    how_it_works = section_content.get("how it works", "")
    steps = []
    matches = list(re.finditer(r"(?m)^\s*\d+[.)]\s+(.+?)\s*$", how_it_works))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(how_it_works)
        text = match.group(1).strip()
        continuation_lines = [
            line.strip()
            for line in how_it_works[match.end():end].splitlines()
            if line.strip()
            and not re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line)
        ]
        if continuation_lines:
            text = f"{text} {' '.join(continuation_lines)}"
        steps.append(text)

    additional_sections = [
        {"title": section.group(1).strip(), "content": section_content[section.group(1).strip().casefold()]}
        for section in sections
        if section.group(1).strip().casefold() not in {
            "quick summary",
            "how it works",
            "in short",
        }
    ]
    takeaway = section_content.get("in short", "")

    return {
        "title": title,
        "introduction": introduction,
        "quick_summary": summary,
        "steps": steps[:5],
        "takeaway": takeaway,
        "additional_sections": additional_sections,
    }


def _run_code_assistant(
    query: str,
    top_k: int = 4,
    mode: Literal["EXPLANATION", "GENERATION"] | None = None,
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("Query must not be empty.")

    from classification import classify_query
    from explanation import explain_query

    intent = mode or str(classify_query(query)).strip().upper()
    trace = [
        {
            "step": "Request Mode" if mode else "Intent Classification",
            "details": f"User selected {intent}" if mode else intent,
            "status": "success",
        }
    ]
    if "EXPLANATION" in intent:
        answer = explain_query(query)
        return {
            "intent": "EXPLANATION",
            "answer": answer,
            **_parse_explanation(answer),
            "code": "",
            "references": [],
            "documents": [],
            "relevance": None,
            "needs_reference_solution": False,
            "trace": trace + [
                {
                    "step": "Explanation LLM",
                    "details": "Generated an educational explanation.",
                    "status": "success",
                }
            ],
        }
    if "GENERATION" not in intent:
        raise RuntimeError(f"Unexpected code assistant intent: {intent}")

    from dataset import vectordb
    from generate import generate_code
    from relevance_checker import check_relevance
    from web_search import search_web

    documents = list(vectordb.similarity_search(query, k=top_k))
    from memory_store import search_solutions

    existing_contents = {doc.page_content for doc in documents}
    for doc in search_solutions(query, k=3):
        if doc.page_content not in existing_contents:
            documents.append(doc)
            existing_contents.add(doc.page_content)
    trace.append(
        {
            "step": "Vector Database Retrieval",
            "details": f"Retrieved {len(documents)} example(s).",
            "status": "success" if documents else "warning",
        }
    )

    evaluation = check_relevance(query, documents)
    relevance_status = evaluation.get("status", "UNCERTAIN")
    trace.append(
        {
            "step": "Relevance Evaluator",
            "details": relevance_status,
            "status": "success" if relevance_status == "RELEVANT" else "warning",
        }
    )
    relevant_ids = set(evaluation.get("relevant_ids", []))
    relevant_documents = [
        doc
        for doc in documents
        if str(doc.metadata.get("task_id", doc.metadata.get("id", "unknown")))
        in relevant_ids
    ]
    references = search_web(query)
    answer = generate_code(query, relevant_documents, web_sources=references)
    trace.extend(
        [
            {
                "step": "Tavily Web Search",
                "details": f"Found {len(references)} web source(s).",
                "status": "success" if references else "warning",
            },
            {
                "step": "Code Generation",
                "details": "Generated code with the available relevant context.",
                "status": "success",
            },
        ]
    )

    return {
        "intent": "GENERATION",
        "answer": answer,
        "code": _extract_code(answer),
        "expected_output": _extract_expected_output(answer),
        "documents": [
            {
                "id": str(
                    doc.metadata.get(
                        "task_id",
                        doc.metadata.get("id", "unknown"),
                    )
                ),
                "content": doc.page_content,
            }
            for doc in documents
        ],
        "relevance": evaluation,
        "needs_reference_solution": relevance_status != "RELEVANT",
        "trace": trace,
        "references": [
            {"title": source["title"], "url": source["url"]}
            for source in references
        ],
    }


def _validate_and_save_reference(request: ReferenceSolutionRequest) -> dict[str, Any]:
    from solution_validator import validate_python_solution

    validation = validate_python_solution(request.code)
    if not validation.get("valid"):
        return {"saved": False, "validation": validation}

    from memory_store import save_solution

    solution_id = save_solution(
        request.task.strip(),
        request.code,
        request.language,
        "passed",
    )
    return {
        "saved": True,
        "solution_id": solution_id,
        "validation": validation,
    }


def _handle_dataset_error(error: Exception) -> HTTPException:
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, SQLValidationError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, TimeoutError):
        return HTTPException(status_code=408, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, RuntimeError):
        return HTTPException(status_code=502, detail=str(error))
    return HTTPException(status_code=500, detail="An unexpected analysis error occurred.")


def _complete_analysis(dataset_id: str, question: str) -> dict[str, Any]:
    generated = generate_sql(dataset_id, question)
    results = execute_sql(dataset_id, generated["sql"])
    explanation = explain_results(question, generated["sql"], results)

    return {
        "dataset_id": dataset_id,
        "question": question,
        "sql": generated["sql"],
        "sql_reason": generated["reason"],
        "results": results,
        "explanation": explanation,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/assistant/chat")
async def code_assistant(
    request: CodeAssistantRequest,
    _: None = Depends(require_login),
) -> dict[str, Any]:
    try:
        return await asyncio.get_running_loop().run_in_executor(
            _code_assistant_executor,
            _run_code_assistant,
            request.query.strip(),
            request.top_k,
            request.mode,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Code assistant request failed: {exc}",
        ) from exc


@app.post("/assistant/validate")
async def validate_code(
    request: CodeActionRequest,
    _: None = Depends(require_login),
) -> dict[str, Any]:
    if not request.approved:
        raise HTTPException(
            status_code=400,
            detail="Confirm that you trust this code before running validation.",
        )

    try:
        return await run_in_threadpool(
            validate_python_solution,
            request.code,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Code validation failed: {exc}",
        ) from exc


@app.post("/assistant/execute")
async def execute_code(
    request: CodeActionRequest,
    _: None = Depends(require_login),
) -> dict[str, Any]:
    if not request.approved:
        raise HTTPException(
            status_code=400,
            detail="Explicit approval is required before executing code.",
        )

    from code_runner import run_python_code

    try:
        return await run_in_threadpool(
            run_python_code,
            request.code,
            request.timeout,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Code execution failed: {exc}",
        ) from exc


@app.post("/assistant/reference-solutions")
async def save_reference_solution(
    request: ReferenceSolutionRequest,
    _: None = Depends(require_login),
) -> dict[str, Any]:
    if not request.approved:
        raise HTTPException(
            status_code=400,
            detail="Confirm that you trust this code before running validation.",
        )
    if not request.save_approved:
        raise HTTPException(
            status_code=400,
            detail="Explicit approval is required before saving a solution.",
        )

    try:
        return await asyncio.get_running_loop().run_in_executor(
            _code_assistant_executor,
            _validate_and_save_reference,
            request,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Reference solution could not be processed: {exc}",
        ) from exc


@app.post("/datasets/upload", status_code=201)
async def upload_dataset(
    file: UploadFile = File(...),
    _: None = Depends(require_login),
) -> dict[str, Any]:
    try:
        contents = await file.read(25 * 1024 * 1024 + 1)
        return await run_in_threadpool(import_csv, file.filename or "", contents)
    except (FileNotFoundError, SQLValidationError, TimeoutError, ValueError, RuntimeError) as exc:
        raise _handle_dataset_error(exc) from exc
    finally:
        await file.close()


@app.get("/datasets/{dataset_id}/schema")
def dataset_schema(
    dataset_id: str,
    _: None = Depends(require_login),
) -> dict[str, Any]:
    try:
        return get_dataset_schema(dataset_id)
    except (FileNotFoundError, SQLValidationError, TimeoutError, ValueError, RuntimeError) as exc:
        raise _handle_dataset_error(exc) from exc


@app.post("/audio/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    _: None = Depends(require_login),
) -> dict[str, str]:
    try:
        contents = await file.read(25 * 1024 * 1024 + 1)
        return await run_in_threadpool(
            transcribe_audio,
            file.filename or "",
            contents,
        )
    except (FileNotFoundError, SQLValidationError, TimeoutError, ValueError, RuntimeError) as exc:
        raise _handle_dataset_error(exc) from exc
    finally:
        await file.close()


@app.post("/datasets/{dataset_id}/sql/generate")
def create_sql(
    dataset_id: str,
    request: AnalysisQuestion,
    _: None = Depends(require_login),
) -> dict[str, str]:
    try:
        return {
            "dataset_id": dataset_id,
            "question": request.question,
            **generate_sql(dataset_id, request.question),
        }
    except (FileNotFoundError, SQLValidationError, TimeoutError, ValueError, RuntimeError) as exc:
        raise _handle_dataset_error(exc) from exc


@app.post("/datasets/{dataset_id}/sql/execute")
def run_sql(
    dataset_id: str,
    request: SQLQuery,
    _: None = Depends(require_login),
) -> dict[str, Any]:
    try:
        return {
            "dataset_id": dataset_id,
            "sql": request.sql,
            "results": execute_sql(dataset_id, request.sql),
        }
    except (FileNotFoundError, SQLValidationError, TimeoutError, ValueError, RuntimeError) as exc:
        raise _handle_dataset_error(exc) from exc


@app.post("/datasets/{dataset_id}/analyze")
def analyze_text(
    dataset_id: str,
    request: AnalysisQuestion,
    _: None = Depends(require_login),
) -> dict[str, Any]:
    try:
        return _complete_analysis(dataset_id, request.question)
    except (FileNotFoundError, SQLValidationError, TimeoutError, ValueError, RuntimeError) as exc:
        raise _handle_dataset_error(exc) from exc


@app.post("/datasets/{dataset_id}/analyze/audio")
async def analyze_audio(
    dataset_id: str,
    file: UploadFile = File(...),
    _: None = Depends(require_login),
) -> dict[str, Any]:
    try:
        contents = await file.read(25 * 1024 * 1024 + 1)
        get_dataset_schema(dataset_id)
        transcription = await run_in_threadpool(
            transcribe_audio,
            file.filename or "",
            contents,
        )
        analysis = await run_in_threadpool(
            _complete_analysis,
            dataset_id,
            transcription["transcript"],
        )
        return {
            **analysis,
            "transcript": transcription["transcript"],
        }
    except (FileNotFoundError, SQLValidationError, TimeoutError, ValueError, RuntimeError) as exc:
        raise _handle_dataset_error(exc) from exc
    finally:
        await file.close()

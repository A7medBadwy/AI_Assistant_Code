import csv
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from faster_whisper import WhisperModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

load_dotenv()

DATA_DIRECTORY = Path(__file__).resolve().parent / "data" / "analysis_datasets"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_DATA_ROWS = 100_000
MAX_RESULT_ROWS = 500
SQL_TIMEOUT_SECONDS = 5
ALLOWED_SQL_FUNCTIONS = {
    "abs",
    "avg",
    "coalesce",
    "count",
    "date",
    "datetime",
    "glob",
    "group_concat",
    "ifnull",
    "instr",
    "julianday",
    "length",
    "like",
    "lower",
    "ltrim",
    "max",
    "min",
    "nullif",
    "printf",
    "replace",
    "round",
    "rtrim",
    "strftime",
    "substr",
    "sum",
    "time",
    "total",
    "trim",
    "typeof",
    "upper",
}
_whisper_model: WhisperModel | None = None
_whisper_lock = threading.Lock()


class SQLValidationError(ValueError):
    """Raised when generated or submitted SQL violates the read-only policy."""


def _dataset_path(dataset_id: str) -> Path:
    try:
        normalized_id = str(uuid.UUID(dataset_id))
    except (ValueError, AttributeError) as exc:
        raise FileNotFoundError("Unknown dataset ID.") from exc

    database_path = DATA_DIRECTORY / f"{normalized_id}.sqlite3"
    if not database_path.is_file():
        raise FileNotFoundError("Unknown dataset ID.")
    return database_path


def _normalize_column_name(value: str, index: int, used: set[str]) -> str:
    name = re.sub(r"\W+", "_", value.strip().lower(), flags=re.UNICODE).strip("_")
    if not name:
        name = f"column_{index}"
    if name[0].isdigit():
        name = f"column_{name}"

    base_name = name
    suffix = 2
    while name in used:
        name = f"{base_name}_{suffix}"
        suffix += 1

    used.add(name)
    return name


def _sqlite_type(values: list[str]) -> str:
    non_empty_values = [value.strip() for value in values if value.strip()]
    if not non_empty_values:
        return "TEXT"

    try:
        for value in non_empty_values:
            int(value)
        return "INTEGER"
    except ValueError:
        pass

    try:
        for value in non_empty_values:
            float(value)
        return "REAL"
    except ValueError:
        return "TEXT"


def import_csv(filename: str, contents: bytes) -> dict[str, Any]:
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError("CSV file exceeds the 25 MB upload limit.")
    if not filename.lower().endswith(".csv"):
        raise ValueError("Unsupported file type. Upload a .csv file.")

    try:
        decoded = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV file must use UTF-8 encoding.") from exc

    reader = csv.reader(io.StringIO(decoded, newline=""))
    try:
        original_headers = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV file is empty.") from exc

    if not original_headers or not any(header.strip() for header in original_headers):
        raise ValueError("CSV file must have a header row.")
    if len(original_headers) > 200:
        raise ValueError("CSV files may contain no more than 200 columns.")

    used_names: set[str] = set()
    columns = [
        _normalize_column_name(header, index, used_names)
        for index, header in enumerate(original_headers, start=1)
    ]
    rows: list[list[str | None]] = []
    for row_number, row in enumerate(reader, start=2):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) != len(columns):
            raise ValueError(
                f"CSV row {row_number} has {len(row)} values; "
                f"expected {len(columns)}."
            )
        rows.append([value.strip() or None for value in row])
        if len(rows) > MAX_DATA_ROWS:
            raise ValueError("CSV files may contain no more than 100,000 data rows.")

    dataset_id = str(uuid.uuid4())
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    database_path = DATA_DIRECTORY / f"{dataset_id}.sqlite3"

    column_types = [
        _sqlite_type([row[index] or "" for row in rows])
        for index in range(len(columns))
    ]
    definitions = ", ".join(
        f'"{name}" {column_type}'
        for name, column_type in zip(columns, column_types)
    )

    try:
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute(f'CREATE TABLE "uploaded_data" ({definitions})')
            if rows:
                placeholders = ", ".join("?" for _ in columns)
                connection.executemany(
                    f'INSERT INTO "uploaded_data" VALUES ({placeholders})',
                    rows,
                )
            connection.commit()
    except (OSError, sqlite3.Error):
        database_path.unlink(missing_ok=True)
        raise

    return {
        "dataset_id": dataset_id,
        "filename": Path(filename).name,
        "row_count": len(rows),
        "columns": [
            {"name": name, "original_name": original, "type": column_type}
            for name, original, column_type in zip(
                columns, original_headers, column_types
            )
        ],
    }


def get_dataset_schema(dataset_id: str) -> dict[str, Any]:
    database_path = _dataset_path(dataset_id)
    with closing(sqlite3.connect(database_path)) as connection:
        connection.row_factory = sqlite3.Row
        table_info = connection.execute('PRAGMA table_info("uploaded_data")')
        columns = [
            {"name": row["name"], "type": row["type"]}
            for row in table_info.fetchall()
        ]
        row_count = connection.execute(
            'SELECT COUNT(*) FROM "uploaded_data"'
        ).fetchone()[0]
        sample_rows = [
            dict(row)
            for row in connection.execute(
                'SELECT * FROM "uploaded_data" LIMIT 5'
            ).fetchall()
        ]

    return {
        "dataset_id": dataset_id,
        "table_name": "uploaded_data",
        "row_count": row_count,
        "columns": columns,
        "sample_rows": sample_rows,
    }


def _get_llm() -> ChatOpenAI:
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openrouter_key and not openai_key:
        raise RuntimeError(
            "Configure OPENROUTER_API_KEY or OPENAI_API_KEY to enable analysis."
        )

    if openrouter_key:
        return ChatOpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            model=os.getenv("OPENROUTER_MODEL", "openrouter/free"),
            temperature=0,
        )

    return ChatOpenAI(
        api_key=openai_key,
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
    )


_SQL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You translate data-analysis questions into safe SQLite SELECT queries.
Return only a JSON object with keys "sql" and "reason".
The only table is uploaded_data. Use only the provided column names.
Generate exactly one read-only SELECT query (WITH ... SELECT is allowed).
Never use PRAGMA, DDL, DML, ATTACH, DETACH, or other tables.
Do not assume values that are not supported by the schema or sample rows.""",
        ),
        (
            "human",
            "Dataset schema and sample rows:\n{schema}\n\n"
            "User's analytical question:\n{question}",
        ),
    ]
)


def _parse_model_json(content: Any) -> dict[str, Any]:
    text = str(content).strip()
    text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("The LLM returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("The LLM response must be a JSON object.")
    return parsed


def generate_sql(dataset_id: str, question: str) -> dict[str, str]:
    if not question.strip():
        raise ValueError("Question must not be empty.")

    schema = get_dataset_schema(dataset_id)
    messages = _SQL_PROMPT.format_messages(
        schema=json.dumps(schema, ensure_ascii=False, default=str),
        question=question.strip(),
    )
    response = _get_llm().invoke(messages)
    result = _parse_model_json(response.content)
    sql = result.get("sql")
    reason = result.get("reason", "")
    if not isinstance(sql, str) or not sql.strip():
        raise RuntimeError("The LLM response did not include a SQL query.")
    if not isinstance(reason, str):
        reason = ""

    validate_sql(sql, dataset_id)
    return {"sql": sql.strip(), "reason": reason.strip()}


def _authorize_sql(
    action: int,
    arg1: str | None,
    arg2: str | None,
    database_name: str | None,
    trigger_name: str | None,
) -> int:
    del database_name, trigger_name

    if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and arg1 == "uploaded_data":
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        function_name = (arg2 or arg1 or "").lower()
        if function_name in ALLOWED_SQL_FUNCTIONS:
            return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def validate_sql(sql: str, dataset_id: str | None = None) -> None:
    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("SQL query must not be empty.")
    if len(sql) > 10_000:
        raise SQLValidationError("SQL query exceeds the 10,000 character limit.")

    without_comments = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", sql, flags=re.DOTALL).strip()
    if not re.match(r"^(SELECT|WITH)\b", without_comments, flags=re.IGNORECASE):
        raise SQLValidationError("Only SELECT queries are allowed.")

    if dataset_id is None:
        return

    database_path = _dataset_path(dataset_id)
    connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
    try:
        connection.set_authorizer(_authorize_sql)
        connection.execute(f"EXPLAIN QUERY PLAN {sql}")
    except sqlite3.Error as exc:
        raise SQLValidationError(f"SQL query is invalid or not allowed: {exc}") from exc
    finally:
        connection.close()


def execute_sql(dataset_id: str, sql: str) -> dict[str, Any]:
    validate_sql(sql, dataset_id)
    database_path = _dataset_path(dataset_id)
    database_uri = f"{database_path.as_uri()}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        connection.row_factory = sqlite3.Row
        connection.set_authorizer(_authorize_sql)
        deadline = time.monotonic() + SQL_TIMEOUT_SECONDS
        connection.set_progress_handler(
            lambda: int(time.monotonic() > deadline),
            1000,
        )
        cursor = connection.execute(sql)
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
        truncated = len(rows) > MAX_RESULT_ROWS
        rows = rows[:MAX_RESULT_ROWS]
        return {
            "columns": columns,
            "rows": [
                {key: row[key] for key in columns}
                for row in rows
            ],
            "row_count": len(rows),
            "truncated": truncated,
        }
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise TimeoutError("SQL query exceeded the 5-second execution limit.") from exc
        raise SQLValidationError(f"SQL could not be executed: {exc}") from exc
    except sqlite3.DatabaseError as exc:
        raise SQLValidationError(f"SQL could not be executed: {exc}") from exc
    finally:
        connection.close()


def explain_results(
    question: str,
    sql: str,
    results: dict[str, Any],
) -> str:
    if not results["rows"]:
        return "The query ran successfully but returned no rows."

    compact_results = {
        "columns": results["columns"],
        "rows": results["rows"][:25],
        "row_count": results["row_count"],
        "truncated": results["truncated"],
    }
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Explain the query results clearly and concisely. "
                "Base every statement only on the supplied result data. "
                "Do not claim statistical significance or infer causation.",
            ),
            (
                "human",
                "Question: {question}\nSQL: {sql}\nResult data: {results}",
            ),
        ]
    )
    messages = prompt.format_messages(
        question=question,
        sql=sql,
        results=json.dumps(compact_results, ensure_ascii=False, default=str),
    )
    explanation = _get_llm().invoke(messages).content
    return str(explanation).strip()


def transcribe_audio(filename: str, contents: bytes) -> dict[str, str]:
    allowed_extensions = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac"}
    extension = Path(filename).suffix.lower()
    if extension not in allowed_extensions:
        raise ValueError(
            "Unsupported audio format. Use WAV, MP3, M4A, MP4, WebM, OGG, or FLAC."
        )
    if not contents:
        raise ValueError("Audio file is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError("Audio file exceeds the 25 MB upload limit.")

    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=extension,
            dir=DATA_DIRECTORY,
            delete=False,
        ) as audio_file:
            audio_file.write(contents)
            temporary_path = audio_file.name

        global _whisper_model
        if _whisper_model is None:
            with _whisper_lock:
                if _whisper_model is None:
                    _whisper_model = WhisperModel(
                        os.getenv("WHISPER_MODEL_SIZE", "base"),
                        device=os.getenv("WHISPER_DEVICE", "cpu"),
                        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
                    )

        segments, _ = _whisper_model.transcribe(temporary_path)
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
        if not transcript:
            raise ValueError("No speech could be recognized in the audio.")
        return {"transcript": transcript}
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)

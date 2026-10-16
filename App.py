import re
import streamlit as st
import json

# Import project modules
try:
    from classification import classify_query
    from explanation import explain_query
    from dataset import vectordb
    from relevance_checker import check_relevance
    from generate import generate_code
    from solution_validator import validate_python_solution
    from code_runner import run_python_code
    from memory_store import search_solutions, save_solution
except ImportError as e:
    st.error(f"Import Error: {e}")
    st.info("Make sure all project Python files exist and their dependencies are installed.")
    st.stop()


# =========================================================
# PAGE CONFIGURATION
# =========================================================
st.set_page_config(
    page_title="CodePilot AI",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================================================
# CUSTOM CSS
# =========================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 10% 0%, rgba(139,92,246,.12), transparent 30%),
        radial-gradient(circle at 90% 5%, rgba(6,182,212,.08), transparent 25%);
}

h1, h2, h3 {
    font-family: 'Space Grotesk', sans-serif !important;
}

.hero {
    padding: 28px;
    border-radius: 22px;
    border: 1px solid rgba(139,92,246,.3);
    background: linear-gradient(
        120deg,
        rgba(139,92,246,.16),
        rgba(6,182,212,.06)
    );
    margin-bottom: 24px;
}

.eyebrow {
    color: #a78bfa;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 3px;
    text-transform: uppercase;
}

.hero-title {
    font-size: 38px;
    font-weight: 700;
    margin: 8px 0;
}

.hero-subtitle {
    color: #9ca3af;
    font-size: 16px;
}

.metric-card {
    padding: 20px;
    border-radius: 16px;
    border: 1px solid rgba(148,163,184,.2);
    background: rgba(30,41,59,.25);
    min-height: 100px;
}

.metric-label {
    color: #9ca3af;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.metric-value {
    font-size: 20px;
    font-weight: 700;
    margin-top: 8px;
}

.stButton > button {
    border-radius: 10px;
    font-weight: 600;
    min-height: 42px;
}

div[data-testid="stChatMessage"] {
    border: 1px solid rgba(148,163,184,.15);
    border-radius: 16px;
    padding: 12px;
    margin-bottom: 10px;
}

.small-muted {
    color: #9ca3af;
    font-size: 12px;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# SESSION STATE
# =========================================================
DEFAULTS = {
    "messages": [],
    "last_query": "",
    "last_code": "",
    "last_documents": [],
    "last_relevance": None,
    "last_validation": None,
    "execution_result": None,
    "pipeline_trace": [],
    "needs_reference_solution": False,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


def add_trace(step, details, status="info"):
    st.session_state.pipeline_trace.append({
        "step": step,
        "details": str(details),
        "status": status,
    })


def extract_code(text):
    """Extract a Python code block from the LLM response."""
    if not text:
        return ""

    match = re.search(
        r"```(?:python|py)?\s*\n(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return match.group(1).strip() if match else text.strip()


def document_id(doc):
    return str(doc.metadata.get("task_id", "unknown"))


def retrieve_documents(query, k=4):
    """Retrieve examples from the main VDB and personal solution VDB."""
    documents = []

    try:
        documents.extend(
            vectordb.similarity_search(query, k=k)
        )
    except Exception as e:
        add_trace("Main VDB", e, "error")

    try:
        personal_docs = search_solutions(query, k=3)

        existing = {
            getattr(doc, "page_content", "")
            for doc in documents
        }

        for doc in personal_docs or []:
            content = getattr(doc, "page_content", "")

            if content not in existing:
                documents.append(doc)
                existing.add(content)

    except Exception as e:
        add_trace("Personal VDB", e, "warning")

    return documents


def filter_relevant_documents(documents, evaluation):
    if not isinstance(evaluation, dict):
        return documents

    relevant_ids = {
        str(item)
        for item in evaluation.get("relevant_ids", [])
    }

    if not relevant_ids:
        return documents

    filtered = [
        doc for doc in documents
        if document_id(doc) in relevant_ids
    ]

    return filtered or documents


# =========================================================
# MAIN AI WORKFLOW
# =========================================================
def process_query(query, top_k=4):

    result = {
        "intent": None,
        "answer": "",
        "code": "",
        "documents": [],
        "relevance": None,
        "needs_reference_solution": False,
        "error": None,
    }

    st.session_state.pipeline_trace = []

    try:
        # STEP 1: CLASSIFICATION
        intent = str(classify_query(query)).strip().upper()
        result["intent"] = intent

        add_trace(
            "Intent Classification",
            intent,
            "success",
        )

        # STEP 2A: EXPLANATION
        if "EXPLANATION" in intent:

            add_trace(
                "Explanation LLM",
                "Generating an educational answer.",
            )

            result["answer"] = explain_query(query)
            return result

        # STEP 2B: GENERATION
        if "GENERATION" not in intent:
            raise ValueError(
                f"Unexpected classification result: {intent}"
            )

        # STEP 3: RETRIEVAL
        documents = retrieve_documents(query, k=top_k)
        result["documents"] = documents

        add_trace(
            "Vector Database Retrieval",
            f"Retrieved {len(documents)} example(s).",
            "success" if documents else "warning",
        )

        # STEP 4: RELEVANCE EVALUATION
        evaluation = check_relevance(query, documents)
        result["relevance"] = evaluation

        relevance_status = (
            evaluation.get("status", "UNCERTAIN")
            if isinstance(evaluation, dict)
            else "UNCERTAIN"
        )

        add_trace(
            "Relevance Evaluator",
            relevance_status,
            "success" if relevance_status == "RELEVANT" else "warning",
        )

        # STEP 5A: RELEVANT EXAMPLES -> GENERATION
        if relevance_status == "RELEVANT":

            relevant_docs = filter_relevant_documents(
                documents,
                evaluation,
            )

            generated_response = generate_code(
                query,
                relevant_docs,
            )

            result["answer"] = generated_response
            result["code"] = extract_code(generated_response)

            add_trace(
                "Code Generation",
                "The LLM generated a solution.",
                "success",
            )

        # STEP 5B: NO CONFIDENTLY RELEVANT EXAMPLES
        else:
            result["needs_reference_solution"] = True

            result["answer"] = (
                "I couldn't confidently find relevant examples "
                "for your programming request.\n\n"
                "Please clarify the task or submit a reference "
                "solution. A solution will only be stored after "
                "validation and your explicit approval."
            )

            add_trace(
                "User Clarification",
                "Waiting for more information or a reference solution.",
                "warning",
            )

        return result

    except Exception as e:
        result["error"] = str(e)
        add_trace("Pipeline Error", e, "error")
        return result


# =========================================================
# SIDEBAR
# =========================================================
with st.sidebar:

    st.markdown("## ⚡ CodePilot AI")
    st.caption("Your AI programming workspace")

    st.divider()

    st.markdown("### Settings")

    top_k = st.slider(
        "Retrieved examples",
        min_value=1,
        max_value=8,
        value=4,
    )

    show_trace = st.toggle(
        "Show pipeline trace",
        value=True,
    )

    show_documents = st.toggle(
        "Show retrieved examples",
        value=True,
    )

    st.divider()

    st.markdown("### Architecture")

    st.markdown("""
    - 🧭 Intent Classification
    - 📚 ChromaDB Retrieval
    - 🧠 Relevance Evaluation
    - ✨ Code Generation
    - 🧪 Code Validation
    - 💾 Personal Solution Memory
    """)

    st.divider()

    if st.button("🧹 Clear conversation", use_container_width=True):

        for key in DEFAULTS:
            st.session_state[key] = DEFAULTS[key].copy() if isinstance(
                DEFAULTS[key], (list, dict)
            ) else DEFAULTS[key]

        st.rerun()

    st.markdown(
        '<p class="small-muted">Python · Streamlit · LangChain · ChromaDB · OpenRouter</p>',
        unsafe_allow_html=True,
    )


# =========================================================
# HEADER
# =========================================================
st.markdown("""
<div class="hero">
    <div class="eyebrow">AI Developer Workspace</div>
    <div class="hero-title">
        Code smarter. <span style="color:#a78bfa;">Build faster.</span>
    </div>
    <div class="hero-subtitle">
        Ask questions, understand programming concepts, and generate
        code with retrieval-augmented generation.
    </div>
</div>
""", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)

cards = [
    ("ROUTING", "Intent-aware"),
    ("KNOWLEDGE", "ChromaDB RAG"),
    ("EVALUATION", "LLM evaluator"),
    ("LANGUAGE", "Python-focused"),
]

for col, (label, value) in zip(
    [col1, col2, col3, col4],
    cards,
):
    with col:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.write("")


# =========================================================
# CHAT HISTORY
# =========================================================
for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        st.markdown(message["content"])

        if message.get("code"):
            st.code(
                message["code"],
                language="python",
            )


# =========================================================
# CHAT INPUT
# =========================================================
query = st.chat_input(
    "Ask for code, an explanation, or a programming solution..."
)

if query:

    st.session_state.messages.append({
        "role": "user",
        "content": query,
    })

    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):

        with st.spinner("CodePilot is processing your request..."):

            result = process_query(
                query,
                top_k=top_k,
            )

        st.session_state.last_query = query
        st.session_state.last_code = result["code"]
        st.session_state.last_documents = result["documents"]
        st.session_state.last_relevance = result["relevance"]
        st.session_state.last_validation = None
        st.session_state.execution_result = None

        if result["error"]:

            st.error(
                f"Something went wrong: {result['error']}"
            )

        else:

            st.caption(
                f"Intent: {result['intent']}"
            )

            st.markdown(result["answer"])

            if result["code"]:

                st.markdown("### Generated Solution")

                st.code(
                    result["code"],
                    language="python",
                )

                st.download_button(
                    "⬇️ Download Python solution",
                    data=result["code"],
                    file_name="solution.py",
                    mime="text/x-python",
                )

            if result["needs_reference_solution"]:
                st.session_state.needs_reference_solution = True

        st.session_state.messages.append({
            "role": "assistant",
            "content": (
                result["error"]
                if result["error"]
                else result["answer"]
            ),
            "code": result["code"],
        })


# =========================================================
# PIPELINE TRACE
# =========================================================
if st.session_state.last_query:

    st.divider()

    left, right = st.columns([1, 1])

    with left:

        st.markdown("### 🧭 Pipeline Trace")

        if show_trace:

            for event in st.session_state.pipeline_trace:

                if event["status"] == "error":
                    st.error(
                        f"**{event['step']}** — {event['details']}"
                    )

                elif event["status"] == "warning":
                    st.warning(
                        f"**{event['step']}** — {event['details']}"
                    )

                elif event["status"] == "success":
                    st.success(
                        f"**{event['step']}** — {event['details']}"
                    )

                else:
                    st.info(
                        f"**{event['step']}** — {event['details']}"
                    )

    with right:

        st.markdown("### 📚 Retrieval Results")

        docs = st.session_state.last_documents
        evaluation = st.session_state.last_relevance

        st.metric(
            "Retrieved examples",
            len(docs),
        )

        if isinstance(evaluation, dict):

            st.metric(
                "Relevance status",
                evaluation.get("status", "UNKNOWN"),
            )

            if evaluation.get("reason"):
                st.caption(evaluation["reason"])

        if show_documents and docs:

            with st.expander("Inspect retrieved documents"):

                for index, doc in enumerate(docs, start=1):

                    st.markdown(
                        f"**Example {index} — ID: {document_id(doc)}**"
                    )

                    st.code(
                        doc.page_content[:4000],
                        language="python",
                    )


# =========================================================
# VALIDATION AND OPTIONAL EXECUTION
# =========================================================
if st.session_state.last_code:

    st.divider()

    st.markdown("### 🧪 Validate Your Solution")

    st.caption(
        "Basic validation checks syntax and execution. "
        "Task-specific tests are required to establish correctness."
    )

    if st.button(
        "Run basic validation",
        type="primary",
    ):

        with st.spinner("Validating solution..."):

            try:

                validation = validate_python_solution(
                    st.session_state.last_code
                )

                st.session_state.last_validation = validation

                if validation.get("valid"):

                    st.success(
                        validation.get(
                            "reason",
                            "Basic validation passed.",
                        )
                    )

                    if validation.get("stdout"):
                        st.code(validation["stdout"])

                else:

                    st.error(
                        validation.get(
                            "reason",
                            "Validation failed.",
                        )
                    )

            except Exception as e:
                st.error(f"Validation error: {e}")

    with st.expander("Advanced: Execute code locally"):

        st.warning(
            "Security warning: the current subprocess runner is not "
            "a secure sandbox. Review and trust the code before execution. "
            "Do not execute arbitrary or malicious code."
        )

        confirm_execution = st.checkbox(
            "I reviewed the code and approve running it on my machine.",
            key="confirm_execution",
        )

        timeout = st.slider(
            "Timeout (seconds)",
            min_value=1,
            max_value=10,
            value=5,
        )

        if st.button(
            "Execute code",
            disabled=not confirm_execution,
        ):

            try:

                execution = run_python_code(
                    st.session_state.last_code,
                    timeout=timeout,
                )

                st.session_state.execution_result = execution

                if execution.get("success"):
                    st.success("Process completed successfully.")
                else:
                    st.error("Process failed or timed out.")

                if execution.get("stdout"):
                    st.markdown("**Standard output**")
                    st.code(execution["stdout"])

                if execution.get("stderr"):
                    st.markdown("**Standard error**")
                    st.code(execution["stderr"])

            except Exception as e:
                st.error(f"Execution error: {e}")


# =========================================================
# USER REFERENCE SOLUTION -> VALIDATE -> OPTIONAL SAVE
# =========================================================
if st.session_state.needs_reference_solution:

    st.divider()

    st.markdown("### 🧠 Add a Reference Solution")

    st.write(
        "The retrieved examples were not confidently relevant. "
        "You can provide a reference solution. It will only be saved "
        "if basic validation passes and you approve saving it."
    )

    with st.form("reference_solution_form"):

        task_description = st.text_area(
            "Task description",
            value=st.session_state.last_query,
        )

        reference_code = st.text_area(
            "Reference Python solution",
            height=220,
            placeholder="Paste your reference solution here...",
        )

        approve_storage = st.checkbox(
            "I approve saving this solution to my personal VDB "
            "if validation passes."
        )

        submit_solution = st.form_submit_button(
            "Validate reference solution",
            type="primary",
        )

    if submit_solution:

        if not task_description.strip() or not reference_code.strip():

            st.error(
                "Please provide both a task description and a solution."
            )

        else:

            try:

                validation = validate_python_solution(
                    reference_code
                )

                if not validation.get("valid"):

                    st.error(
                        validation.get(
                            "reason",
                            "Validation failed.",
                        )
                    )

                else:

                    st.success(
                        validation.get(
                            "reason",
                            "Basic validation passed.",
                        )
                    )

                    st.warning(
                        "Basic validation does not prove algorithmic correctness. "
                        "Add task-specific tests before treating the solution as verified."
                    )

                    if approve_storage:

                        save_result = save_solution(
                            task=task_description,
                            code=reference_code,
                            language="python",
                            validation_status="passed",
                        )

                        st.success(
                            "Solution submitted to the personal vector database."
                        )

                        st.caption(str(save_result))

                        st.session_state.needs_reference_solution = False

                    else:

                        st.info(
                            "The solution was not saved because you did not approve storage."
                        )

            except Exception as e:
                st.error(f"Could not process reference solution: {e}")


# =========================================================
# FOOTER
# =========================================================
st.divider()

st.markdown(
    """
    <div class="small-muted" style="text-align:center;">
        CodePilot AI · Retrieval-Augmented Coding Assistant
        <br>
        Always review generated code before executing it.
    </div>
    """,
    unsafe_allow_html=True,
)


from langchain_classic.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_community.embeddings import HuggingFaceBgeEmbeddings


DB_PATH = "./data/chroma_database"
COLLECTION_NAME = "user_verified_solutions"

embedding_model = HuggingFaceBgeEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)

vectorstore = Chroma(
    collection_name=COLLECTION_NAME,
    persist_directory=DB_PATH,
    embedding_function=embedding_model,
)


def save_solution(
    task: str,
    code: str,
    language: str = "python",
    validation_status: str = "passed",
) -> str:
    """Store a validated solution in ChromaDB."""

    if not task.strip() or not code.strip():
        raise ValueError("Task and code must not be empty.")

    if validation_status != "passed":
        raise ValueError("Only validated solutions can be stored.")

    import uuid

    solution_id = str(uuid.uuid4())

    document = Document(
        page_content=(
            f"Task:\n{task}\n\n"
            f"Language: {language}\n\n"
            f"Solution:\n{code}"
        ),
        metadata={
            "language": language,
            "validation_status": validation_status,
            "source": "user_submitted",
        },
    )

    vectorstore.add_documents(
        documents=[document],
        ids=[solution_id],
    )

    return solution_id


def search_solutions(query: str, k: int = 3) -> list:
    """Retrieve previously stored solutions."""

    if not query.strip():
        return []

    return vectorstore.similarity_search(query, k=k)


"""if __name__ == "__main__":
    print("User solution memory is ready.")
    print("Stored solutions:", vectorstore._collection.count())



task = "Write a Python function that adds two numbers."

code = """""""
def add(a, b):
    return a + b
"""

"""# This example is for testing only.
# In the full application, call this after validation
# and explicit user confirmation.
solution_id = save_solution(
    task=task,
    code=code,
    language="python",
    validation_status="passed",
)

print("Saved solution ID:", solution_id)

results = search_solutions(
    "Create a function to sum two numbers.",
    k=3,
)

for doc in results:
    print("\n--- Retrieved solution ---")
    print(doc.page_content)
    print(doc.metadata)
"""
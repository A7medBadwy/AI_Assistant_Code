
import uuid

from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client.http.models import Distance, VectorParams

from dataset import client as shared_client, embedding_model


DB_PATH = "./data/qdrant_database"
COLLECTION_NAME = "user_verified_solutions"

# Reuse the same Qdrant client instance so multiple modules do not lock the same local database path.
client = shared_client

# Ensure the personal-solution collection exists in the shared database.
if not client.collection_exists(COLLECTION_NAME):
    embedding_size = len(embedding_model.embed_query("test"))
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=embedding_size,
            distance=Distance.COSINE,
        ),
    )

vectorstore = QdrantVectorStore(
    client=client,
    collection_name=COLLECTION_NAME,
    embedding=embedding_model,
)


def save_solution(
    task: str,
    code: str,
    language: str = "python",
    validation_status: str = "passed",
) -> str:
    """Store a validated solution in Qdrant."""

    if not task.strip() or not code.strip():
        raise ValueError("Task and code must not be empty.")

    if validation_status != "passed":
        raise ValueError("Only validated solutions can be stored.")

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
    """Retrieve previously stored solutions from Qdrant."""

    if not query.strip():
        return []

    return vectorstore.similarity_search(query, k=k)


"""if __name__ == "__main__":
    print("User solution memory is ready.")

    print(
        "Stored solutions:",
        client.count(
            collection_name=COLLECTION_NAME,
            exact=True,
        ).count,
    )

    task = "Write a Python function that adds two numbers."
    code = "def add(a, b):\n    return a + b"
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

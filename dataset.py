import atexit
import importlib.util
import os
import shutil
import subprocess
import sys

REQUIRED_PACKAGES = [
    "datasets",
    "langchain-core",
    "langchain-community",
    "langchain-qdrant",
    "qdrant-client",
    "sentence-transformers",
]


def _module_name(package_name: str) -> str:
    return package_name.replace("-", "_")


def ensure_required_packages() -> None:
    missing = [
        package_name
        for package_name in REQUIRED_PACKAGES
        if importlib.util.find_spec(_module_name(package_name)) is None
    ]

    if not missing:
        return

    commands = []
    if os.name == "nt" and shutil.which("py"):
        commands.append(["py", "-m", "pip", "install", *missing])
    commands.append([sys.executable, "-m", "pip", "install", *missing])

    for command in commands:
        try:
            subprocess.check_call(command)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    raise RuntimeError(
        "Missing required packages: " + ", ".join(missing) + ". "
        "Install them with: py -m pip install " + " ".join(missing)
    )


ensure_required_packages()

from datasets import load_dataset
from langchain_core.documents import Document
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

# Configuration
DB_PATH = "./data/qdrant_database"
COLLECTION_NAME = "humaneval_code_examples"

# Shared module state used by App.py and scripts
client = QdrantClient(path=DB_PATH)
atexit.register(client.close)
embedding_model = HuggingFaceBgeEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)


def initialize_vectorstore() -> QdrantVectorStore:
    global vectordb

    if not client.collection_exists(COLLECTION_NAME):
        embedding_size = len(embedding_model.embed_query("test"))
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=embedding_size,
                distance=Distance.COSINE,
            ),
        )

    vectordb = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding=embedding_model,
    )

    return vectordb


def load_humaneval_documents() -> list[Document]:
    dataset = load_dataset("openai/openai_humaneval")
    documents = []

    for item in dataset["test"]:
        content = (
            f"Problem:\n{item['prompt']}\n\n"
            f"Reference Solution:\n{item['canonical_solution']}"
        )
        documents.append(
            Document(
                page_content=content,
                metadata={
                    "task_id": item["task_id"],
                    "entry_point": item["entry_point"],
                },
            )
        )

    return documents


vectordb = initialize_vectorstore()


def main() -> None:
    documents = load_humaneval_documents()
    vectordb = initialize_vectorstore()

    if client.count(collection_name=COLLECTION_NAME, exact=True).count == 0:
        vectordb.add_documents(documents=documents)
        print("HumanEval documents inserted into Qdrant.")
    else:
        print("Connected to existing Qdrant collection.")

    count = client.count(collection_name=COLLECTION_NAME, exact=True).count
    print("Qdrant collection:", COLLECTION_NAME)
    print("Stored documents:", count)

    query = "Write a Python function to check if a number is prime."
    results = vectordb.similarity_search(query, k=3)

    for doc in results:
        print("\nMetadata:", doc.metadata)
        print(doc.page_content)
        print("-" * 50)


if __name__ == "__main__":
    main()

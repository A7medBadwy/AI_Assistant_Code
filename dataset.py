
from datasets import load_dataset
from langchain_core.documents import Document
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_classic.vectorstores import Chroma

# 1. Load the dataset
dataset = load_dataset("openai/openai_humaneval")

# 2. Prepare LangChain documents
documents = []

for item in dataset["test"]:
    content = (
        f"Problem:\n{item['prompt']}\n\n"
        f"Reference Solution:\n{item['canonical_solution']}"
    )

    document = Document(
        page_content=content,
        metadata={
            "task_id": item["task_id"],
            "entry_point": item["entry_point"]
        }
    )

    documents.append(document)

# 3. Initialize the embedding model
embedding_model = HuggingFaceBgeEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)

# 4. Store documents in ChromaDB
vectorstore = Chroma.from_documents(
    documents=documents,
    embedding=embedding_model,
    collection_name="humaneval_code_examples",
    persist_directory="./data/chroma_database"
)

#print("Stored documents:", vectorstore._collection.count())

vectordb=Chroma(persist_directory="./data/chroma_database",
                embedding_function=embedding_model,
                collection_name="humaneval_code_examples")


"""if __name__ == "__main__":
    query = "Write a Python function to check if a number is prime."
    results = vectordb.similarity_search_with_score(query, k=5)
    for doc, score in results:
        print(f"Score: {score}\nDocument:\n{doc.page_content}\n{'-'*40}")
"""

# ingest.py
import os
import chromadb
from chromadb.utils import embedding_functions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CASE_STUDIES_DIR = os.path.join(BASE_DIR, "case_studies")
CHROMA_DB_PATH = os.path.join(BASE_DIR, "chroma_db")

BATCH_SIZE = 500  # safely under ChromaDB's max of 5461


def ingest():
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    collection = client.get_or_create_collection(
        name="case_studies",
        embedding_function=embedder
    )

    # Load all case files into memory
    documents, ids, metadatas = [], [], []
    for filename in os.listdir(CASE_STUDIES_DIR):
        if filename.endswith(".txt"):
            filepath = os.path.join(CASE_STUDIES_DIR, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if not text:
                continue
            case_id = filename.replace(".txt", "")
            documents.append(text)
            ids.append(case_id)
            metadatas.append({"filename": filename})

    print(f"Loaded {len(documents)} case files. Ingesting in batches of {BATCH_SIZE}...")

    # Upsert in batches to stay under ChromaDB's batch size limit
    total = len(documents)
    for i in range(0, total, BATCH_SIZE):
        batch_docs = documents[i:i + BATCH_SIZE]
        batch_ids = ids[i:i + BATCH_SIZE]
        batch_meta = metadatas[i:i + BATCH_SIZE]
        collection.upsert(documents=batch_docs, ids=batch_ids, metadatas=batch_meta)
        print(f"  Upserted {min(i + BATCH_SIZE, total)}/{total}...")

    print(f"\nDone. {total} cases ingested into ChromaDB.")


if __name__ == "__main__":
    ingest()
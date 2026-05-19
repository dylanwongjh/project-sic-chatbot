# reset_and_reingest.py
import os
import chromadb
from chromadb.utils import embedding_functions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CASE_STUDIES_DIR = os.path.join(BASE_DIR, "case_studies")
CHROMA_DB_PATH = os.path.join(BASE_DIR, "chroma_db")
BATCH_SIZE = 500

embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

# Wipe the existing collection entirely
client.delete_collection("case_studies")
print("Deleted existing collection.")

# Recreate it fresh
collection = client.create_collection(
    name="case_studies",
    embedding_function=embedder
)

# Load only enriched files — those containing '=== CASE STUDY PROFILE ==='
documents, ids, metadatas = [], [], []
skipped = 0

for filename in sorted(os.listdir(CASE_STUDIES_DIR)):
    if not filename.endswith(".txt"):
        continue
    filepath = os.path.join(CASE_STUDIES_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if "=== CASE STUDY PROFILE ===" not in text:
        skipped += 1
        continue
    documents.append(text)
    ids.append(filename.replace(".txt", ""))
    metadatas.append({"filename": filename})

print(f"Found {len(documents)} enriched files, skipped {skipped} plain files.")

# Ingest in batches
total = len(documents)
for i in range(0, total, BATCH_SIZE):
    collection.upsert(
        documents=documents[i:i + BATCH_SIZE],
        ids=ids[i:i + BATCH_SIZE],
        metadatas=metadatas[i:i + BATCH_SIZE]
    )
    print(f"  Upserted {min(i + BATCH_SIZE, total)}/{total}...")

print(f"\nDone. {total} enriched cases ingested.")
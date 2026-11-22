import io
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from app.config import settings
from app.database import get_db_connection


def process_pdf_bytes(file_bytes: bytes, filename: str):
    if not file_bytes:
        raise ValueError("Uploaded file is empty.")
    # Allow a deterministic fallback embedding when OPENAI_API_KEY is not provided
    pdf_file = io.BytesIO(file_bytes)
    reader = PdfReader(pdf_file)

    text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted + "\n"

    if not text.strip():
        raise ValueError("No readable text was found in the PDF.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )
    chunks = splitter.split_text(text)

    # Generate embeddings using OpenAI if available, otherwise use a deterministic local embedding
    if settings.OPENAI_API_KEY:
        embeddings_model = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
        embeddings = embeddings_model.embed_documents(chunks)
    else:
        import hashlib
        import numpy as np

        def _deterministic_emb(s: str, dim: int = 1536):
            h = hashlib.sha256(s.encode("utf-8")).digest()
            seed = int.from_bytes(h[:8], "big") % (2**32)
            rng = np.random.RandomState(seed)
            v = rng.rand(dim).astype(float)
            norm = np.linalg.norm(v)
            if norm > 0:
                v = v / norm
            return v.tolist()

        embeddings = [_deterministic_emb(c) for c in chunks]

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                    cur.execute(
                        """
                        INSERT INTO document_chunks (filename, chunk_index, content, embedding)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (filename, idx, chunk, emb),
                    )
    finally:
        conn.close()

    return len(chunks)

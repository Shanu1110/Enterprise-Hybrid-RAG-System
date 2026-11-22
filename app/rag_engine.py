import numpy as np
from rank_bm25 import BM25Okapi
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.config import settings
from app.database import get_db_connection


def reciprocal_rank_fusion(dense_results, sparse_results, k=60):
    scores = {}

    def add_ranks(results):
        for rank, item in enumerate(results):
            doc_id, content = item["id"], item["content"]
            if doc_id not in scores:
                scores[doc_id] = {"content": content, "score": 0.0}
            scores[doc_id]["score"] += 1.0 / (k + rank + 1)

    add_ranks(dense_results)
    add_ranks(sparse_results)

    return sorted(scores.values(), key=lambda x: x["score"], reverse=True)


def query_hybrid_rag(query_text: str):
    query_text = query_text.strip()
    if not query_text:
        raise ValueError("Query cannot be empty.")
    # Allow deterministic local operation when OPENAI_API_KEY is not provided (for offline testing)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, content FROM document_chunks;")
            all_rows = cur.fetchall()
            if not all_rows:
                return "No documents uploaded yet. Please ingest documents first.", []

            doc_ids = [row[0] for row in all_rows]
            corpus = [row[1] for row in all_rows]

            tokenized_corpus = [doc.lower().split() for doc in corpus]
            bm25 = BM25Okapi(tokenized_corpus)

            tokenized_query = query_text.lower().split()
            bm25_scores = bm25.get_scores(tokenized_query)
            top_bm25_indices = np.argsort(bm25_scores)[::-1][:10]

            sparse_results = [
                {"id": doc_ids[idx], "content": corpus[idx]}
                for idx in top_bm25_indices
            ]

            # Compute query embedding (OpenAI if available, otherwise deterministic local)
            if settings.OPENAI_API_KEY:
                embeddings_model = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
                query_emb = embeddings_model.embed_query(query_text)
            else:
                import hashlib

                def _deterministic_emb(s: str, dim: int = 1536):
                    h = hashlib.sha256(s.encode("utf-8")).digest()
                    seed = int.from_bytes(h[:8], "big") % (2**32)
                    rng = np.random.RandomState(seed)
                    v = rng.rand(dim).astype(float)
                    norm = np.linalg.norm(v)
                    if norm > 0:
                        v = v / norm
                    return v.tolist()

                query_emb = _deterministic_emb(query_text)

            cur.execute(
                """
                SELECT id, content
                FROM document_chunks
                ORDER BY embedding <=> %s::vector
                LIMIT 10;
                """,
                (query_emb,),
            )
            dense_rows = cur.fetchall()
    finally:
        conn.close()

    dense_results = [{"id": row[0], "content": row[1]} for row in dense_rows]

    fused_docs = reciprocal_rank_fusion(dense_results, sparse_results)
    top_context = "\n\n---\n\n".join([doc["content"] for doc in fused_docs[:5]])

    # If no OPENAI API key is configured, synthesize a conservative answer from the retrieved context
    if not settings.OPENAI_API_KEY:
        # Simple exact-term check: if any token from the query appears in context, return the matching sentences
        qtokens = [t.lower() for t in query_text.split() if len(t) > 2]
        context_sentences = [s.strip() for s in top_context.split('.') if s.strip()]
        matches = []
        for sent in context_sentences:
            s_low = sent.lower()
            if any(q in s_low for q in qtokens):
                matches.append(sent)
        if matches:
            answer = "\n\n".join(matches[:3])
            return answer, [doc["content"] for doc in fused_docs[:5]]
        else:
            return "Information is unavailable in the ingested documents.", [doc["content"] for doc in fused_docs[:5]]

    prompt_template = ChatPromptTemplate.from_template(
        """You are a precise enterprise search assistant. Answer the user prompt based strictly on the provided context.
        If the answer cannot be found in the context, clearly state that the information is unavailable.

        Context:
        {context}

        Question:
        {question}

        Answer:"""
    )

    llm = ChatOpenAI(model=settings.OPENAI_CHAT_MODEL, temperature=0)
    chain = prompt_template | llm
    response = chain.invoke({"context": top_context, "question": query_text})

    return response.content, [doc["content"] for doc in fused_docs[:5]]

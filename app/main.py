from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from app.database import init_db
from app.ingestion import process_pdf_bytes
from app.rag_engine import query_hybrid_rag

app = FastAPI(title="Enterprise Knowledge Graph & Hybrid RAG API")


@app.on_event("startup")
def startup_event():
    init_db()


class QueryRequest(BaseModel):
    query: str


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    contents = await file.read()
    try:
        chunks_created = process_pdf_bytes(contents, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"message": f"Successfully ingested {file.filename}", "chunks": chunks_created}


@app.post("/query")
async def run_query(request: QueryRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    try:
        answer, context_chunks = query_hybrid_rag(request.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"answer": answer, "sources": context_chunks}

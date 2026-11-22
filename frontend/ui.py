import os
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
REQUEST_TIMEOUT = 60

st.set_page_config(page_title="Enterprise Hybrid RAG System", layout="wide")

st.title("Enterprise Knowledge Graph & Hybrid RAG System")
st.markdown("Powered by **PostgreSQL + pgvector**, **BM25**, and **Reciprocal Rank Fusion**.")

st.sidebar.header("Document Ingestion")
uploaded_file = st.sidebar.file_uploader("Upload PDF Document", type=["pdf"])


def api_error_message(response):
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = response.text
    return detail or f"Request failed with status {response.status_code}."


if uploaded_file is not None:
    if st.sidebar.button("Ingest Document"):
        with st.spinner("Processing and indexing..."):
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
            try:
                res = requests.post(f"{API_URL}/upload", files=files, timeout=REQUEST_TIMEOUT)
                if res.status_code == 200:
                    st.sidebar.success(res.json().get("message"))
                else:
                    st.sidebar.error(f"Error: {api_error_message(res)}")
            except requests.RequestException as exc:
                st.sidebar.error(f"Failed to connect to API: {exc}")

st.divider()

user_query = st.text_input("Ask a question about your ingested enterprise documents:")

if st.button("Search & Answer", type="primary"):
    if not user_query.strip():
        st.warning("Please enter a valid query.")
    else:
        with st.spinner("Performing hybrid search and synthesizing answer..."):
            try:
                res = requests.post(
                    f"{API_URL}/query",
                    json={"query": user_query.strip()},
                    timeout=REQUEST_TIMEOUT,
                )
                if res.status_code == 200:
                    data = res.json()

                    st.subheader("Answer")
                    st.write(data["answer"])

                    with st.expander("Retrieved Context Chunks (RRF Top 5)"):
                        for i, source in enumerate(data.get("sources", []), 1):
                            st.markdown(f"**Chunk {i}:**")
                            st.info(source)
                else:
                    st.error(f"Error: {api_error_message(res)}")
            except requests.RequestException as exc:
                st.error(f"Failed to connect to backend service: {exc}")

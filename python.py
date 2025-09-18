import streamlit as st
import pandas as pd
import numpy as np
import faiss
import google.generativeai as genai
import os
import pickle
import re

# ----------------- CONFIG -----------------
genai.configure(api_key="REVOKED_CREDENTIAL_REMOVED")  
MODEL_NAME = "gemini-1.5-flash"
EMBED_MODEL = "models/text-embedding-004"

llm = genai.GenerativeModel(MODEL_NAME)

DATA_PATH = r"C:\Users\anuva\OneDrive\Desktop\argofloat\FloatChat\indian_ocean_profiles_01Jan2025_31Jan2025.parquet"
INDEX_PATH = "faiss_index.bin"
DOCS_PATH = "documents.pkl"


# ----------------- LOAD DATA -----------------
@st.cache_data
def load_data():
    return pd.read_parquet(DATA_PATH)

df = load_data()


# ----------------- BUILD OR LOAD INDEX -----------------
def build_and_save_index(df: pd.DataFrame, sample_size: int = 200):
    documents = []

    # Schema
    schema_text = " | ".join([f"{col}: {str(df[col].dtype)}" for col in df.columns])
    documents.append("COLUMNS: " + schema_text)

    # Sample rows
    sample_df = df.sample(n=min(sample_size, len(df)), random_state=42)
    for _, row in sample_df.iterrows():
        text = " | ".join([f"{col}: {row[col]}" for col in df.columns])
        documents.append(text)

    # Create embeddings
    vectors = []
    progress = st.progress(0)
    for i, doc in enumerate(documents):
        emb = genai.embed_content(model=EMBED_MODEL, content=doc)
        vectors.append(emb["embedding"])
        progress.progress((i + 1) / len(documents))

    vectors = np.array(vectors).astype("float32")

    # Build FAISS index
    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

    # Save
    faiss.write_index(index, INDEX_PATH)
    with open(DOCS_PATH, "wb") as f:
        pickle.dump(documents, f)

    return index, documents


@st.cache_resource
def load_index_and_docs(df):
    if os.path.exists(INDEX_PATH) and os.path.exists(DOCS_PATH):
        index = faiss.read_index(INDEX_PATH)
        with open(DOCS_PATH, "rb") as f:
            documents = pickle.load(f)
        return index, documents
    else:
        return build_and_save_index(df)


index, documents = load_index_and_docs(df)


# ----------------- RAG PIPELINE -----------------
def retrieve_context(query: str, k: int = 5):
    q_emb = genai.embed_content(model=EMBED_MODEL, content=query)["embedding"]
    q_emb = np.array([q_emb]).astype("float32")
    distances, indices = index.search(q_emb, k)
    return [documents[i] for i in indices[0]]


def clean_code(output: str) -> str:
    """Remove markdown fences + extra text, keep only code."""
    code = output.strip()
    code = re.sub(r"```.*?```", lambda m: m.group(0).replace("```python", "").replace("```", ""), code, flags=re.S)
    code = code.replace("```python", "").replace("```", "")
    return code.strip()


def generate_query(user_query: str, context: str):
    prompt = f"""
You are a data assistant.
Convert the user query into valid Python/Pandas code that runs directly on dataframe `df`.

Rules:
- Output only valid Python code, nothing else.
- No markdown, no explanation.
- If query asks for a value, assign it to variable `result`.

User query: "{user_query}"
Context (schema + sample rows):
{context}
"""
    response = llm.generate_content(prompt)
    return clean_code(response.text)


def execute_query(code: str, df: pd.DataFrame):
    local_env = {"df": df, "pd": pd, "np": np}
    try:
        # Try eval (expressions)
        return eval(code, local_env)
    except SyntaxError:
        try:
            # Ensure result variable exists if assignment is missing
            if "result" not in code:
                code = f"result = {code}"
            exec(code, local_env)
            return local_env.get("result", "✅ Executed (no result returned)")
        except Exception as e:
            return f"⚠️ Error running query: {e}"


def answer_from_data(user_query: str, df: pd.DataFrame):
    retrieved = retrieve_context(user_query, k=5)
    context = "\n".join(retrieved)

    query_code = generate_query(user_query, context)
    result = execute_query(query_code, df)

    return query_code, result


# ----------------- STREAMLIT UI -----------------
st.set_page_config(page_title="FLOATCHAT-OCEAN DATA BOT", page_icon="🌊", layout="wide")
st.title("🌊 FLOAT-CHAT")
st.markdown("Chat with the Indian Ocean Argo float dataset (Jan 2025).")

if "messages" not in st.session_state:
    st.session_state["messages"] = []

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("Ask about the ocean dataset..."):
    st.session_state["messages"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing data..."):
            query_code, result = answer_from_data(user_input, df)

            st.markdown("**🔎 Generated Pandas Query:**")
            st.code(query_code, language="python")

            st.markdown("**📊 Result:**")
            if isinstance(result, (pd.DataFrame, pd.Series)):
                st.dataframe(result)
            else:
                st.write(result)

    st.session_state["messages"].append({"role": "assistant", "content": str(result)})

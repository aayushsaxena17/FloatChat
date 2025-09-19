import os
import re
import pickle
import faiss
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import folium
from streamlit_folium import st_folium
import google.generativeai as genai

# ----------------- CONFIG -----------------
genai.configure(api_key="REVOKED_CREDENTIAL_REMOVED")  # 🔑 Replace with your Gemini API key
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
    schema_text = " | ".join([f"{col}: {str(df[col].dtype)}" for col in df.columns])
    documents.append("COLUMNS: " + schema_text)

    sample_df = df.sample(n=min(sample_size, len(df)), random_state=42)
    for _, row in sample_df.iterrows():
        text = " | ".join([f"{col}: {row[col]}" for col in df.columns])
        documents.append(text)

    vectors = []
    progress = st.progress(0)
    for i, doc in enumerate(documents):
        emb = genai.embed_content(model=EMBED_MODEL, content=doc)
        vectors.append(emb["embedding"])
        progress.progress((i + 1) / len(documents))

    vectors = np.array(vectors).astype("float32")
    dim = vectors.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(vectors)

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
- For map queries asking for a specific location (e.g. max/min), the output should be a DataFrame with one or more rows.

User query: "{user_query}"
Context (schema + sample rows):
{context}
"""
    response = llm.generate_content(prompt)
    return clean_code(response.text)

def execute_query(code: str, df: pd.DataFrame):
    local_env = {"df": df, "pd": pd, "np": np}
    try:
        return eval(code, local_env)
    except SyntaxError:
        try:
            if "result" not in code:
                code = f"result = {code}"
            exec(code, local_env)
            return local_env.get("result", "✅ Executed (no result returned)")
        except Exception as e:
            return f"⚠️ Error running query: {e}"

# ----------------- MAIN DATA HANDLER -----------------
def answer_from_data(user_query: str, df: pd.DataFrame):
    lat_col = next((col for col in df.columns if col.lower().strip() in ['latitude', 'lat']), None)
    lon_col = next((col for col in df.columns if col.lower().strip() in ['longitude', 'lon']), None)

    if "map" in user_query.lower() or "location" in user_query.lower():
        if not lat_col or not lon_col:
            return {"type": "text", "content": "⚠️ Dataset has no `latitude` and `longitude` columns."}

        # --- Specific cases like max/min queries ---
        if "max" in user_query.lower() or "min" in user_query.lower() or "with" in user_query.lower():
            retrieved = retrieve_context(user_query, k=5)
            context = "\n".join(retrieved)
            query_code = generate_query(user_query, context)
            result_df = execute_query(query_code, df)

            if isinstance(result_df, pd.Series):
                result_df = pd.DataFrame([result_df])

            if isinstance(result_df, pd.DataFrame) and not result_df.empty:
                mean_lat = result_df[lat_col].mean()
                mean_lon = result_df[lon_col].mean()
                m = folium.Map(location=[mean_lat, mean_lon], zoom_start=3)

                for _, row in result_df.iterrows():
                    lat = row[lat_col]
                    lon = row[lon_col]
                    popup_text = f"Profile ID: {row.get('profile_id', 'N/A')}<br>Temperature: {row.get('temperature', 'N/A')}<br>Salinity: {row.get('salinity', 'N/A')}"
                    folium.Marker(
                        location=[lat, lon],
                        popup=folium.Popup(popup_text, max_width=300),
                        icon=folium.Icon(color="red", icon="info-sign")
                    ).add_to(m)

                return {"type": "map", "content": m._repr_html_()}

            else:
                return {"type": "text", "content": "⚠️ Could not find the specified location. Please try a different query."}

        # --- Default Arabian Sea map (show only 5 floats) ---
        else:
            m = folium.Map(location=[15, 65], zoom_start=4)
            subset = df[(df[lat_col].between(5, 25)) & (df[lon_col].between(55, 75))]

            # sample up to 5 floats
            subset = subset.sample(n=min(5, len(subset)), random_state=42)

            for _, row in subset.iterrows():
                folium.CircleMarker(
                    location=[row[lat_col], row[lon_col]],
                    radius=5,
                    color="blue",
                    fill=True,
                    fill_opacity=0.8,
                    popup=f"Profile ID: {row.get('profile_id', 'N/A')}"
                ).add_to(m)
            return {"type": "map", "content": m._repr_html_()}

    # ----------------- Normal RAG flow -----------------
    retrieved = retrieve_context(user_query, k=5)
    context = "\n".join(retrieved)
    query_code = generate_query(user_query, context)
    result = execute_query(query_code, df)

    key_columns = ["salinity", "temperature", "pressure", "oxygen"]
    for col in key_columns:
        if col in df.columns and col in user_query.lower():
            if ("mean" not in user_query.lower()) and ("average" not in user_query.lower()):
                result = df[col].mean()
                query_code = f"result = df['{col}'].mean()"
                break

    return {"type": "code", "query": query_code, "output": result}

# ----------------- STREAMLIT UI -----------------
st.set_page_config(page_title="FLOATCHAT-OCEAN DATA BOT", page_icon="🌊", layout="wide")

with st.sidebar:
    st.title("⚙️ Settings")
    show_code = st.checkbox("Show generated Pandas code", value=True)
    st.info("Tip: Try:\n- 'Show me average temperature by depth'\n- 'Plot salinity vs temperature'\n- 'Show me the location map'\n- 'Give me a map of the float with max salinity'")

st.title("🌊 FLOAT-CHAT")
st.markdown("Interact with the **Indian Ocean Argo float dataset** using natural language.")

if "messages" not in st.session_state:
    st.session_state["messages"] = []

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        if msg["type"] == "text":
            st.markdown(msg["content"])
        elif msg["type"] == "code":
            st.markdown("**📝 Generated Pandas Query:**")
            st.code(msg["query"], language="python")
            if isinstance(msg["output"], (pd.DataFrame, pd.Series)):
                st.markdown("**📊 Result:**")
                st.dataframe(msg["output"])
            else:
                st.markdown("**📊 Result:**")
                st.write(msg["output"])
        elif msg["type"] == "map":
            st.markdown("**🗺️ Location Map:**")
            st.components.v1.html(msg["content"], height=500)

if user_input := st.chat_input("Ask about the ocean dataset..."):
    st.session_state["messages"].append({"role": "user", "content": user_input, "type": "text"})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("🔎 Analyzing data..."):
            result = answer_from_data(user_input, df)

            if result["type"] == "map":
                st.markdown("**🗺️ Location Map:**")
                st.components.v1.html(result["content"], height=500)
                st.session_state["messages"].append({"role": "assistant", "type": "map", "content": result["content"]})
            elif result["type"] == "text":
                st.write(result["content"])
                st.session_state["messages"].append({"role": "assistant", "type": "text", "content": result["content"]})
            elif result["type"] == "code":
                query_code = result["query"]
                output = result["output"]

                if show_code and query_code:
                    st.markdown("**📝 Generated Pandas Query:**")
                    st.code(query_code, language="python")

                if isinstance(output, (pd.DataFrame, pd.Series)):
                    st.markdown("**📊 Result:**")
                    st.dataframe(output)
                elif "plot" in user_input.lower() or "graph" in user_input.lower():
                    try:
                        st.markdown("**📈 Generated Plot:**")
                        fig, ax = plt.subplots(figsize=(6, 4))
                        exec(query_code, {"df": df, "pd": pd, "np": np, "plt": plt, "ax": ax})
                        st.pyplot(fig)
                    except Exception as e:
                        st.error(f"⚠️ Could not generate plot: {e}")
                        st.write(output)
                else:
                    st.markdown("**📊 Result:**")
                    st.write(output)

                st.session_state["messages"].append({
                    "role": "assistant",
                    "type": "code",
                    "query": query_code,
                    "output": output
                })

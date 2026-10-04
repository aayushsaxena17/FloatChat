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
from datetime import datetime

# ----------------- CONFIG -----------------
genai.configure(api_key="REVOKED_CREDENTIAL_REMOVED")  # 🔑 Replace with your Gemini API key
MODEL_NAME = "gemini-1.5-flash"
EMBED_MODEL = "models/text-embedding-004"
llm = genai.GenerativeModel(MODEL_NAME)

DATA_PATH = r"C:\Users\aayus\OneDrive\Desktop\Awein\AgroFloat\CLEANED_indian_ocean_2025.parquet"
INDEX_PATH = "faiss_index.bin"
DOCS_PATH = "documents.pkl"

# ----------------- STREAMLIT UI -----------------
st.set_page_config(
    page_title="FLOATCHAT-OCEAN DATA BOT", 
    page_icon="🌊", 
    layout="wide",
    initial_sidebar_state="expanded"
)

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

# def generate_query(user_query: str, context: str):
#     prompt = f"""
#     You are a data assistant. Convert the user query into valid Python/Pandas code that runs directly on dataframe df.
    
#     Rules:
#     - Output only valid Python code, nothing else.
#     - No markdown, no explanation.
#     - If query asks for a value, assign it to variable result.
#     - For map queries asking for a specific location (e.g. max/min), the output should be a DataFrame with one or more rows.
    
#     User query: "{user_query}"
#     Context (schema + sample rows): {context}
#     """
#     response = llm.generate_content(prompt)
#     return clean_code(response.text)

def generate_query(user_query: str, context: str):
    prompt = f"""
    You are a data assistant. Convert the user query into valid Python/Pandas code that runs directly on dataframe df.

    Rules:
    - Output only valid Python code, nothing else.
    - No markdown, no explanation.
    - If query asks for a value, assign it to variable result.
    - For map queries asking for a specific location (e.g. max/min), the output should be a DataFrame with one or more rows.
    - If using datetime comparisons:
        * Always convert df['date'] with df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        * Use pd.Timestamp.now() (timezone-naive) for current time.
        * Normalize the cutoff with .normalize() before subtracting offsets (e.g. pd.Timestamp.now().normalize() - pd.DateOffset(months=6)).
    - If grouping by month, always use df['date'].dt.to_period('M').
    
    User query: "{user_query}"
    Context (schema + sample rows): {context}
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
# ----------------- MAIN DATA HANDLER -----------------
def answer_from_data(user_query: str, df: pd.DataFrame):
    # --- Greeting handler ---
    greetings = ["hi", "hello", "hey", "good morning", "good evening", "good afternoon", "namaste", "hola"]
    if user_query.lower().strip() in greetings:
        return {
            "type": "text",
            "content": "👋 Hello! I'm FloatChat. Ask me anything about the Indian Ocean Argo float dataset 🌊"
        }

    lat_col = next((col for col in df.columns if col.lower().strip() in ['latitude', 'lat']), None)
    lon_col = next((col for col in df.columns if col.lower().strip() in ['longitude', 'lon']), None)
    
    if "map" in user_query.lower() or "location" in user_query.lower():
        if not lat_col or not lon_col:
            return {"type": "text", "content": "⚠️ Dataset has no latitude and longitude columns."}
        
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


# ----------------- SESSION STATE INITIALIZATION -----------------
def initialize_session_state():
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "chat_sessions" not in st.session_state:
        st.session_state["chat_sessions"] = {}
    if "current_session_id" not in st.session_state:
        st.session_state["current_session_id"] = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        st.session_state["chat_sessions"][st.session_state["current_session_id"]] = {
            "title": "New Chat",
            "messages": [],
            "created_at": datetime.now()
        }

def create_new_chat():
    # Save current session
    if st.session_state["messages"]:
        st.session_state["chat_sessions"][st.session_state["current_session_id"]]["messages"] = st.session_state["messages"]
        # Update title with first message
        if st.session_state["messages"]:
            first_user_msg = next((msg["content"] for msg in st.session_state["messages"] if msg["role"] == "user"), "New Chat")
            st.session_state["chat_sessions"][st.session_state["current_session_id"]]["title"] = first_user_msg[:50] + "..." if len(first_user_msg) > 50 else first_user_msg
    
    # Create new session
    new_session_id = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    st.session_state["current_session_id"] = new_session_id
    st.session_state["chat_sessions"][new_session_id] = {
        "title": "New Chat",
        "messages": [],
        "created_at": datetime.now()
    }
    st.session_state["messages"] = []

def load_chat_session(session_id):
    if session_id in st.session_state["chat_sessions"]:
        # Save current session first
        if st.session_state["messages"]:
            st.session_state["chat_sessions"][st.session_state["current_session_id"]]["messages"] = st.session_state["messages"]
        
        # Load selected session
        st.session_state["current_session_id"] = session_id
        st.session_state["messages"] = st.session_state["chat_sessions"][session_id]["messages"]



# Initialize session state
initialize_session_state()

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1e3c72 0%, #2a5298 100%);
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
        color: white;
        text-align: center;
    }
    
    .chat-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.5rem;
        background-color: #f0f2f6;
        border-radius: 8px;
        margin-bottom: 1rem;
    }
    
    .new-chat-btn {
        background: linear-gradient(45deg, #ff6b6b, #ee5a52);
        color: white;
        border: none;
        padding: 0.5rem 1rem;
        border-radius: 20px;
        cursor: pointer;
        font-weight: bold;
    }
    
    .chat-session-item {
        padding: 0.5rem;
        border-radius: 8px;
        cursor: pointer;
        margin: 0.25rem 0;
        border-left: 3px solid transparent;
        transition: all 0.3s ease;
    }
    
    .chat-session-item:hover {
        background-color: #e8f4fd;
        border-left-color: #2a5298;
    }
    
    .active-session {
        background-color: #d4edda !important;
        border-left-color: #28a745 !important;
    }
    
    .dataset-info {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 1rem 0;
    }
    
    .feature-card {
        background-color: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin: 0.5rem 0;
        border-left: 4px solid #2a5298;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("""
    <div class="main-header">
        <h2>🌊 FloatChat</h2>
        <p>Ocean Data Explorer</p>
    </div>
    """, unsafe_allow_html=True)
    
    # New Chat Button
    if st.button("🆕 New Chat", key="new_chat", help="Start a new conversation"):
        create_new_chat()
        st.rerun()
    
    st.markdown("---")
    
    # Chat History
    st.subheader("💬 Chat History")
    
    # Sort sessions by creation time (newest first)
    sorted_sessions = sorted(
        st.session_state["chat_sessions"].items(),
        key=lambda x: x[1]["created_at"],
        reverse=True
    )
    
    for session_id, session_data in sorted_sessions:
        is_active = session_id == st.session_state["current_session_id"]
        
        # Create a container for each chat session
        with st.container():
            col1, col2 = st.columns([4, 1])
            
            with col1:
                if st.button(
                    f"💭 {session_data['title']}", 
                    key=f"load_{session_id}",
                    help=f"Created: {session_data['created_at'].strftime('%Y-%m-%d %H:%M')}",
                    type="primary" if is_active else "secondary"
                ):
                    load_chat_session(session_id)
                    st.rerun()
            
            with col2:
                if st.button("🗑️", key=f"delete_{session_id}", help="Delete chat"):
                    if len(st.session_state["chat_sessions"]) > 1:
                        del st.session_state["chat_sessions"][session_id]
                        if session_id == st.session_state["current_session_id"]:
                            # Switch to the most recent remaining session
                            remaining_sessions = list(st.session_state["chat_sessions"].keys())
                            st.session_state["current_session_id"] = remaining_sessions[0]
                            st.session_state["messages"] = st.session_state["chat_sessions"][remaining_sessions[0]]["messages"]
                        st.rerun()
    
    st.markdown("---")
    
    # Settings
    st.subheader("⚙️ Settings")
    show_code = st.checkbox("Show generated Pandas code", value=True)
    
    # Dataset Info
    st.markdown("""
    <div class="dataset-info">
        <h4>📊 Dataset Info</h4>
        <p><strong>Records:</strong> {:,}</p>
        <p><strong>Columns:</strong> {}</p>
        <p><strong>Period:</strong> Jan-Sep 2025</p>
        <p><strong>Region:</strong> Indian Ocean</p>
    </div>
    """.format(len(df), len(df.columns)), unsafe_allow_html=True)
    
    # Example queries
    st.subheader("💡 Example Queries")
    example_queries = [
        "Show me the average salinity and temperature for floats in the Arabian Sea during March 2025.h",
        "Plot the average temperature vs depth profile for March 2025",
        "Show me the monthly average salinity in the Indian ocean for the last 6 months",
        "Show me the location of the float that recorded the maximum temperature",
        "Find the nearest ARGO float to 10°N, 70°E and show its latest profile",
        "Plot temperature vs depth profile for the float with maximum salinity in January 2025."
    ]
    
    for query in example_queries:
        if st.button(f"🔍 {query}", key=f"example_{hash(query)}", help="Click to use this query"):
            st.session_state.example_query = query
    
    # Statistics
    with st.expander("📈 Quick Stats"):
        if 'temperature' in df.columns:
            st.metric("Avg Temperature", f"{df['temperature'].mean():.2f}°C")
        if 'salinity' in df.columns:
            st.metric("Avg Salinity", f"{df['salinity'].mean():.2f}")
        if 'pressure' in df.columns:
            st.metric("Max Depth", f"{df['pressure'].max():.0f} dbar")

# Main content area
col1, col2 = st.columns([3, 1])

with col1:
    st.markdown("""
    <div class="main-header">
        <h1>🌊 FLOAT-CHAT</h1>
        <p>Interact with the <strong>Indian Ocean Argo float dataset</strong> using natural language</p>
    </div>
    """, unsafe_allow_html=True)

with col2:
    current_session = st.session_state["chat_sessions"][st.session_state["current_session_id"]]
    st.info(f"**Current Chat:** {current_session['title']}\n\n**Messages:** {len(st.session_state['messages'])}")

# Display chat messages
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        if msg["type"] == "text":
            st.markdown(msg["content"])
        elif msg["type"] == "code":
            if show_code and "query" in msg:
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

# Handle example query selection
if hasattr(st.session_state, 'example_query'):
    user_input = st.session_state.example_query
    delattr(st.session_state, 'example_query')
else:
    user_input = st.chat_input("Ask about the ocean dataset... 🌊")

# Process user input
if user_input:
    # Add user message
    st.session_state["messages"].append({
        "role": "user", 
        "content": user_input, 
        "type": "text"
    })
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Generate and display assistant response
    with st.chat_message("assistant"):
        with st.spinner("🔎 Analyzing data..."):
            result = answer_from_data(user_input, df)
            
            if result["type"] == "map":
                st.markdown("**🗺️ Location Map:**")
                st.components.v1.html(result["content"], height=500)
                st.session_state["messages"].append({
                    "role": "assistant", 
                    "type": "map", 
                    "content": result["content"]
                })
                
            elif result["type"] == "text":
                st.write(result["content"])
                st.session_state["messages"].append({
                    "role": "assistant", 
                    "type": "text", 
                    "content": result["content"]
                })
                
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
                        fig, ax = plt.subplots(figsize=(10, 6))
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
    
    # Auto-save current session
    st.session_state["chat_sessions"][st.session_state["current_session_id"]]["messages"] = st.session_state["messages"]
    
    # Update session title if it's still "New Chat"
    if st.session_state["chat_sessions"][st.session_state["current_session_id"]]["title"] == "New Chat":
        title = user_input[:50] + "..." if len(user_input) > 50 else user_input
        st.session_state["chat_sessions"][st.session_state["current_session_id"]]["title"] = title

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; padding: 1rem;">
    <p>🌊 <strong>FloatChat</strong> - Powered by Argo Float Data & Generative AI</p>
    <p><em>Explore ocean data through natural language conversations</em></p>
</div>
""", unsafe_allow_html=True)
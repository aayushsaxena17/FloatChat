import streamlit as st
import pandas as pd
import google.generativeai as genai   

genai.configure(api_key="REVOKED_CREDENTIAL_REMOVED")   
MODEL_NAME = "gemini-1.5-flash"      
model = genai.GenerativeModel(MODEL_NAME)


@st.cache_data
def load_data():
    df = pd.read_parquet(
        r"C:\Users\anuva\OneDrive\Desktop\argofloat\FloatChat\indian_ocean_profiles_01Jan2025_31Jan2025.parquet"
    )
    return df

df = load_data()

def ask_gemini(prompt: str) -> str:
    response = model.generate_content(prompt)
    return response.text

def answer_from_data(user_query: str, df: pd.DataFrame) -> str:
    preview = df.head(50).to_csv(index=False)

    prompt = f"""
You are a data assistant.
The user asked: "{user_query}"

Here is a preview of the dataset (Indian Ocean Argo float profiles, Jan 2025):
{preview}

Based on the dataset, answer the user query.
If exact data is not available, explain how the user could explore it with pandas.
"""

    return ask_gemini(prompt)

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
            response = answer_from_data(user_input, df)
            st.markdown(response)

    st.session_state["messages"].append({"role": "assistant", "content": response})

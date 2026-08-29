"""
Minimal Streamlit chat UI for the Starcare RAG backend.

Run the backend first:
    uvicorn app.main:app --reload --port 8000

Then run this:
    streamlit run streamlit_app.py
"""

import uuid

import requests
import streamlit as st

API_URL = "http://localhost:8000/api/v1/chat"

st.set_page_config(page_title="Starcare Assistant", page_icon="💬")
st.title("Starcare Support Assistant")

# --- session setup -----------------------------------------------------
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {"role": "user"/"assistant", "content": str}

role = st.sidebar.radio("Role", ["caregiver", "admin"])
if st.sidebar.button("Reset chat"):
    st.session_state.messages = []
    requests.post("http://localhost:8000/api/v1/chat/reset", json={"user_id": st.session_state.user_id})
    st.rerun()

# --- render past messages ----------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- handle new input ----------------------------------------------------
if prompt := st.chat_input("Ask something about Starcare..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                resp = requests.post(
                    API_URL,
                    json={"user_id": st.session_state.user_id, "role": role, "message": prompt},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                answer = data.get("answer", "No answer returned.")
            except requests.exceptions.RequestException as e:
                answer = f"⚠️ Could not reach the backend at {API_URL}: {e}"

            st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
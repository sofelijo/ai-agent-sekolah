import os
import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain

# === Load API Key ===
load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

# === Baca file isi lokal ===
def baca_file(path: str) -> str:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return f"⚠️ File {path} tidak ditemukan."

# === Streamlit UI ===
st.set_page_config(page_title="AI Sekolah SDN Semper Barat 01", page_icon="🏫")
st.title("📚 AI Sekolah SDN Semper Barat 01")
st.caption("Asisten AI resmi sekolah. Silakan ajukan pertanyaan.")

# === Cache vectorstore dari kecerdasan.md
@st.cache_resource
def buat_vectorstore():
    isi = baca_file("kecerdasan.md")
    doc = Document(page_content=isi, metadata={"sumber": "kecerdasan.md"})
    embedding = OpenAIEmbeddings(model="text-embedding-3-small")
    return FAISS.from_documents([doc], embedding)

vectorstore = buat_vectorstore()
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

# === Prompt dari file prompt.md
system_prompt = baca_file("prompt.md")

prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(system_prompt),
    MessagesPlaceholder(variable_name="chat_history"),
    HumanMessagePromptTemplate.from_template("{input}")
])

# === Setup LLM & Chain
llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)
combine_chain = create_stuff_documents_chain(llm=llm, prompt=prompt)
retrieval_chain = create_retrieval_chain(retriever=retriever, combine_docs_chain=combine_chain)

# === Chat Session
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

st.markdown("### 💬 Ajukan Pertanyaan")
pertanyaan = st.chat_input("Contoh: 'Siapa kepala sekolah?' atau 'Apa syarat PPDB?'")

# Tampilkan histori chat
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Tangani pertanyaan baru
if pertanyaan:
    with st.chat_message("user"):
        st.markdown(pertanyaan)
    st.session_state.chat_history.append({"role": "user", "content": pertanyaan})

    with st.chat_message("assistant"):
        with st.spinner("🤖 Menyusun jawaban..."):
            result = retrieval_chain.invoke({
                "input": pertanyaan,
                "chat_history": st.session_state.chat_history
            })
            jawaban = result["answer"]
            st.markdown(jawaban)
            st.session_state.chat_history.append({"role": "assistant", "content": jawaban})

import os
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain.chains import RetrievalQA
from langchain.prompts import ChatPromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

load_dotenv()

def build_qa_chain():
    # Baca isi file kecerdasan.md
    with open("kecerdasan.md", "r", encoding="utf-8") as f:
        content = f.read()

    doc = Document(page_content=str(content), metadata={"sumber": "kecerdasan.md"})

    # Buat retriever dari FAISS
    embedding = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents([doc], embedding)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # Gunakan LLM
    llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")

    # ==== Tambahkan personality ASKA ====
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Kamu adalah ASKA 🤖✨, Agent AI Sekolah Kita. Jawab semua pertanyaan dengan gaya ramah, santai, dan cocok untuk anak SD dan orang tua. Sisipkan emoji agar lebih seru!"),
        ("human", "{question}")
    ])

    # Buat QA Chain dengan prompt custom
    return RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": prompt}
    )

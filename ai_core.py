import os
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain.chains import RetrievalQA
from langchain.prompts import ChatPromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.text_splitter import RecursiveCharacterTextSplitter  # ✅ Tambahan penting

load_dotenv()

def build_qa_chain():
    # Baca isi file kecerdasan.md
    with open("kecerdasan.md", "r", encoding="utf-8") as f:
        content = f.read()

    # ✅ Split dokumen per bagian (agar hari tidak tercampur)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,      # bisa disesuaikan tergantung ukuran rata-rata per kelas
        chunk_overlap=50     # agar koneksi antarbab tidak terputus
    )
    docs = text_splitter.create_documents([content])

    # Buat retriever dari FAISS vector store
    embedding = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents(docs, embedding)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # Gunakan ChatOpenAI model termurah dan cerdas
    llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")

    # Tambahkan personality ASKA
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "Nama aku ASKA. Jawab pertanyaan dengan gaya Gen-Z yang santai, ramah, dan pakai emoji. "
            "Selalu sebut nama **'ASKA'** secara alami. Gunakan info ini:\n\n{context}"
        ),
        (
            "human",
            "{question}"
        )
    ])

    # Bangun QA Chain dengan prompt khusus
    return RetrievalQA.from_chain_type(
        llm=llm,
        retriever=retriever,
        chain_type="stuff",
        chain_type_kwargs={"prompt": prompt}
    )

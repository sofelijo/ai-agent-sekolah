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

    # Siapkan dokumen dari isi file
    doc = Document(page_content=str(content), metadata={"sumber": "kecerdasan.md"})

    # Buat retriever dari FAISS vector store
    embedding = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents([doc], embedding)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # Gunakan ChatOpenAI model termurah dan cerdas
    llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")

    # Tambahkan personality ASKA
    prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "Nama aku ASKA. Jawab pertanyaan dengan gaya Gen-Z yang santai, ramah, dan pakai emoji. Selalu sebut nama **'ASKA'** secara alami. Gunakan info ini:\n\n{context}"
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

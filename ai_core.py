import os
from dotenv import load_dotenv

from langchain_core.documents import Document
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

load_dotenv()

def build_qa_chain():
    # Baca isi file kecerdasan.md
    with open("kecerdasan.md", "r", encoding="utf-8") as f:
        content = f.read()

    # Siapkan dokumen
    doc = Document(page_content=str(content), metadata={"sumber": "kecerdasan.md"})


    # Buat retriever dari FAISS
    embedding = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents([doc], embedding)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # Gunakan ChatOpenAI sebagai LLM
    llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")

    return RetrievalQA.from_chain_type(llm=llm, retriever=retriever)

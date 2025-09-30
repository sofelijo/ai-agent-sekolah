import os
from dotenv import load_dotenv

from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter

load_dotenv()

def build_qa_chain():
    llm = ChatOpenAI(temperature=0, model="gpt-4o-mini")
    embedding = OpenAIEmbeddings()

    with open("kecerdasan.md", "r", encoding="utf-8") as f:
        content = f.read()

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,       # 💡 aman untuk tabel panjang
        chunk_overlap=100      # supaya konteks antar chunk tetap nyambung
    )

    docs = text_splitter.create_documents([content])
    vectorstore = FAISS.from_documents(docs, embedding)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

    # TAHAP 1: BUAT RETRIEVER YANG SADAR HISTORY
    # Tujuan: Mengubah pertanyaan user (misal: "kalau untuk SMA?") menjadi pertanyaan mandiri
    # berdasarkan history (misal: "berapa besaran KJP untuk SMA?").
    contextualize_q_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "Diberikan riwayat chat dan pertanyaan terbaru, formulasikan ulang pertanyaan itu menjadi pertanyaan mandiri tanpa mengubah isinya."),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )
    history_aware_retriever = create_history_aware_retriever(
        llm, retriever, contextualize_q_prompt
    )

    # TAHAP 2: BUAT PROMPT UNTUK MENJAWAB PERTANYAAN
    # Prompt ini akan menerima dokumen (context) dari retriever di atas.
    qa_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "Nama aku ASKA. Jawab pertanyaan dengan gaya Gen-Z yang santai, ramah, dan pakai emoji. "
                     "Selalu sebut nama **'ASKA'** secara alami. Gunakan info dari konteks ini:\n\n{context}"),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
        ]
    )

    # TAHAP 3: BUAT CHAIN UNTUK MENGGABUNGKAN DOKUMEN KE PROMPT
    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)

    # TAHAP 4: GABUNGKAN SEMUANYA MENJADI SATU RAG CHAIN UTUH
    # Alurnya: Input -> History-Aware Retriever -> Question-Answer Chain -> Output
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

    return rag_chain
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
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY (atau OPENAI_API_KEY sebagai fallback) harus di-set untuk menjalankan ASKA."
        )

    api_base = (
        os.getenv("ASKA_OPENAI_API_BASE")
        or os.getenv("OPENAI_API_BASE")
        or os.getenv("ASKA_GROQ_API_BASE")
        or "https://api.groq.com/openai/v1"
    )

    llm = ChatOpenAI(
        temperature=float(os.getenv("ASKA_QA_TEMPERATURE", "0")),
        model=os.getenv("ASKA_QA_MODEL", "llama-3.1-8b-instant"),
        max_tokens=int(os.getenv("ASKA_QA_MAX_TOKENS", "300")),  # ⬅️ batas jawaban agar tidak ngalor ngidul
        openai_api_key=api_key,
        openai_api_base=api_base,
    )

    embedding_api_key = os.getenv("ASKA_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not embedding_api_key:
        raise RuntimeError(
            "Setidaknya satu dari ASKA_EMBEDDING_API_KEY atau OPENAI_API_KEY dibutuhkan untuk membuat embedding."
        )

    embedding_api_base = (
        os.getenv("ASKA_EMBEDDING_API_BASE")
        or os.getenv("OPENAI_EMBEDDING_API_BASE")
        or "https://api.openai.com/v1"
    )

    embedding = OpenAIEmbeddings(
        model=os.getenv("ASKA_EMBEDDING_MODEL", "text-embedding-3-large"),
        openai_api_key=embedding_api_key,
        openai_api_base=embedding_api_base,
    )

    with open("kecerdasan.md", "r", encoding="utf-8") as f:
        content = f.read()

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n|", "\n## ", "\n\n", "\n", " ", ""],  # urutkan dari yang paling “kuat”
        keep_separator=True
    )

    docs = text_splitter.create_documents([content])
    vectorstore = FAISS.from_documents(docs, embedding)
    retriever = vectorstore.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 3, "fetch_k": 25, "lambda_mult": 0.8}
    )
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

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter

from knowledge_loader import load_kecerdasan

try:  # opsional, hanya dipakai bila backend lokal diaktifkan
    from langchain_huggingface import HuggingFaceEmbeddings
except Exception:  # pragma: no cover - optional dependency
    HuggingFaceEmbeddings = None  # type: ignore[misc,assignment]

load_dotenv()


def _load_cached_vectorstore(
    *,
    cache_dir: Path,
    metadata_path: Path,
    doc_hash: str,
    chunk_size: int,
    chunk_overlap: int,
    embedding_signature: dict[str, str],
    embedding,
) -> Optional[FAISS]:
    if not cache_dir.exists() or not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text())
    except Exception:
        return None
    if (
        metadata.get("doc_hash") != doc_hash
        or metadata.get("chunk_size") != chunk_size
        or metadata.get("chunk_overlap") != chunk_overlap
        or metadata.get("embedding_signature") != embedding_signature
    ):
        return None
    try:
        return FAISS.load_local(
            str(cache_dir),
            embeddings=embedding,
            allow_dangerous_deserialization=True,
        )
    except Exception as exc:  # pragma: no cover - cache corruption/environment issues
        print(f"[RAG] Cache FAISS tidak dapat dimuat ({exc}). Memulai ulang pembuatan index...")
        return None


def _save_vectorstore_cache(
    *,
    vectorstore: FAISS,
    cache_dir: Path,
    metadata_path: Path,
    metadata: dict[str, object],
) -> None:
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    vectorstore.save_local(str(cache_dir))
    metadata_path.write_text(json.dumps(metadata, indent=2))


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
        max_tokens=int(os.getenv("ASKA_QA_MAX_TOKENS", "1000")),  # ⬅️ batas jawaban agar tidak ngalor ngidul
        openai_api_key=api_key,
        openai_api_base=api_base,
    )

    backend_pref = os.getenv("ASKA_EMBEDDING_BACKEND", "auto").lower()
    embedding_api_key = os.getenv("ASKA_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    embedding_signature: dict[str, str]

    if backend_pref not in {"auto", "openai", "local"}:
        backend_pref = "auto"

    use_local = backend_pref == "local" or (backend_pref == "auto" and not embedding_api_key)
    if use_local:
        if HuggingFaceEmbeddings is None:
            raise RuntimeError(
                "Embedding backend disetel ke 'local' tetapi dependensi langchain-huggingface/sentence-transformers belum terpasang.\n"
                "Jalankan: pip install langchain-huggingface sentence-transformers torch>=1.11.0"
            )
        local_device = os.getenv("ASKA_EMBEDDING_DEVICE", "cpu")
        local_model = os.getenv(
            "ASKA_EMBEDDING_MODEL_LOCAL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        embedding = HuggingFaceEmbeddings(
            model_name=local_model,
            model_kwargs={"device": local_device},
            encode_kwargs={"normalize_embeddings": True},
        )
        embedding_signature = {
            "provider": "huggingface",
            "model": local_model,
            "device": local_device,
        }
    else:
        if not embedding_api_key:
            raise RuntimeError(
                "Embedding backend disetel ke OpenAI, tetapi ASKA_EMBEDDING_API_KEY / OPENAI_API_KEY belum diisi."
            )
        embedding_api_base = (
            os.getenv("ASKA_EMBEDDING_API_BASE")
            or os.getenv("OPENAI_EMBEDDING_API_BASE")
            or "https://api.openai.com/v1"
        )

        openai_embedding_model = os.getenv("ASKA_EMBEDDING_MODEL", "text-embedding-3-large")
        embedding = OpenAIEmbeddings(
            model=openai_embedding_model,
            openai_api_key=embedding_api_key,
            openai_api_base=embedding_api_base,
        )
        embedding_signature = {
            "provider": "openai",
            "model": openai_embedding_model,
            "api_base": embedding_api_base,
        }

    content = load_kecerdasan()

    chunk_size = int(os.getenv("ASKA_CHUNK_SIZE", "500"))
    chunk_overlap = int(os.getenv("ASKA_CHUNK_OVERLAP", "50"))
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n|", "\n## ", "\n\n", "\n", " ", ""],  # urutkan dari yang paling “kuat”
        keep_separator=True
    )

    doc_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    cache_root = Path(os.getenv("ASKA_VECTORSTORE_PATH", ".aska_vectorstore"))
    index_name = os.getenv("ASKA_VECTORSTORE_INDEX", "kecerdasan")
    cache_dir = cache_root / index_name
    metadata_path = cache_root / f"{index_name}.meta.json"

    vectorstore = _load_cached_vectorstore(
        cache_dir=cache_dir,
        metadata_path=metadata_path,
        doc_hash=doc_hash,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        embedding_signature=embedding_signature,
        embedding=embedding,
    )
    if vectorstore is None:
        docs = text_splitter.create_documents([content])
        vectorstore = FAISS.from_documents(docs, embedding)
        _save_vectorstore_cache(
            vectorstore=vectorstore,
            cache_dir=cache_dir,
            metadata_path=metadata_path,
            metadata={
                "doc_hash": doc_hash,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "embedding_signature": embedding_signature,
            },
        )

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

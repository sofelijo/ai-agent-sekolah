import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
import os
import pdfplumber

# === Load API Key ===
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

st.set_page_config(page_title="AI Sekolah", page_icon="🏫")
st.title("📚 AI Sekolah SDN Semper Barat 01")
st.caption("Jawab pertanyaan berdasarkan file PPDB dan Jadwal Pelajaran")

# === Fungsi membaca PDF lokal ===
def baca_pdf(path):
    text = ""
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        return text.strip()
    except Exception as e:
        st.error(f"Gagal membaca {path}: {e}")
        return ""

# === Baca dua file PDF yang sudah disiapkan ===
pdf_ppdb = baca_pdf("syarat-ppdb.pdf")
pdf_jadwal = baca_pdf("jadwal-pelajaran.pdf")

# === Tampilkan isi PDF untuk pengecekan internal (bisa disembunyikan) ===
with st.expander("🔍 Lihat isi dokumen"):
    st.subheader("📝 SYARAT PPDB")
    st.text_area("Isi PPDB", pdf_ppdb, height=150)
    st.subheader("📅 JADWAL PELAJARAN")
    st.text_area("Isi Jadwal", pdf_jadwal, height=150)

# === Input pertanyaan dari user ===
pertanyaan = st.text_input("Tanyakan sesuatu (misalnya: Jadwal kelas 1 hari Senin):")
st.markdown("Contoh: `Apa syarat masuk kelas 1?` atau `Kapan pelajaran Matematika kelas 5?`")

# === Validasi dan proses jawaban AI ===
if pertanyaan:
    if not (pdf_ppdb or pdf_jadwal):
        st.error("Dokumen belum berhasil dibaca.")
    else:
        with st.spinner("Sedang memproses jawaban dari AI..."):
            try:
                response = client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {
                            "role": "system",
                            "content": f"""
Kamu adalah AI sekolah dasar di Jakarta Utara. Berikut dua dokumen resmi sekolah:

== SYARAT PPDB ==
{pdf_ppdb}

== JADWAL PELAJARAN ==
{pdf_jadwal}

Jawablah pertanyaan pengguna berdasarkan dokumen di atas. Jika informasi tidak tersedia, jawab dengan jujur. Gunakan bahasa sopan dan mudah dimengerti.
"""
                        },
                        {"role": "user", "content": pertanyaan}
                    ]
                )
                jawaban = response.choices[0].message.content
                st.success("Jawaban AI:")
                st.markdown(jawaban)
            except Exception as e:
                st.error(f"Terjadi error saat menjawab: {e}")
else:
    st.info("Silakan ketik pertanyaan di atas.")

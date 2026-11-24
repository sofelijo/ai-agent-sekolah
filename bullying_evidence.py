"""Bounded media validation and private evidence storage, outside every static directory."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import warnings
from PIL import Image
from werkzeug.utils import secure_filename

MAX_FILES = 3
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_REQUEST_BYTES = 41 * 1024 * 1024
IMAGE_TYPES = {'JPEG': ('jpg', 'image/jpeg'), 'PNG': ('png', 'image/png'), 'WEBP': ('webp', 'image/webp')}
VIDEO_TYPES = {'mp4': 'video/mp4', 'mov': 'video/quicktime', 'webm': 'video/webm'}

class EvidenceError(ValueError):
    pass


def evidence_root():
    return Path(os.getenv('BULLYING_EVIDENCE_DIR') or Path(__file__).resolve().parent / 'instance/private/bullying').resolve()


def detect_media(path, filename):
    extension=Path(filename).suffix.lower().lstrip('.')
    if extension in {'jpg','jpeg','png','webp'}:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    media=IMAGE_TYPES.get(image.format)
                    if not media or image.width*image.height>20_000_000 or getattr(image,'n_frames',1)>1:
                        raise EvidenceError('Foto harus JPG, PNG, atau WebP, maksimal 20 megapiksel, tanpa animasi.')
                    image.verify()
                with Image.open(path) as image:image.load()
            return media
        except EvidenceError:raise
        except Exception as exc:raise EvidenceError('Foto tidak valid atau rusak. Pilih berkas foto lain.') from exc
    if extension not in VIDEO_TYPES:
        raise EvidenceError('Bukti harus foto JPG/PNG/WebP atau video MP4/MOV/WebM.')
    with open(path,'rb') as file:header=file.read(16)
    if ((extension in {'mp4','mov'} and header[4:8]!=b'ftyp') or
            (extension=='webm' and not header.startswith(b'\x1aE\xdf\xa3'))):
        raise EvidenceError('Isi berkas tidak sesuai dengan format video.')
    try:
        result=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file',
            '-show_entries','stream=codec_type:format=format_name,duration','-of','json',str(path)],
            capture_output=True,text=True,timeout=10,check=True)
        info=json.loads(result.stdout);duration=float(info['format']['duration'])
        if not any(s.get('codec_type')=='video' for s in info.get('streams',[])) or not 0<duration<=180:
            raise EvidenceError('Video harus berisi gambar bergerak dan berdurasi maksimal 3 menit.')
        formats=info['format'].get('format_name','').split(',')
        if (extension=='webm' and 'webm' not in formats) or (extension in {'mp4','mov'} and 'mov' not in formats):
            raise EvidenceError('Format video tidak didukung.')
    except EvidenceError:raise
    except FileNotFoundError as exc:raise EvidenceError('Unggahan video sedang tidak tersedia. Coba foto atau kirim tanpa bukti dahulu.') from exc
    except Exception as exc:raise EvidenceError('Video tidak valid atau rusak. Pilih video lain.') from exc
    return extension,VIDEO_TYPES[extension]


def remove_evidence(items):
    for item in items:
        path=evidence_path(item)
        if path:path.unlink(missing_ok=True)


def evidence_path(item):
    file_id=item.get('id','');extension=item.get('extension','')
    if not isinstance(file_id,str) or not re.fullmatch(r'[a-f0-9]{32}',file_id) or extension not in {'jpg','png','webp','mp4','mov','webm'}:
        return None
    root=evidence_root();path=root/(file_id+'.'+extension)
    if path.is_symlink() or path.resolve().parent!=root:return None
    return path


def store_evidence(files):
    files=[file for file in files if file.filename]
    if len(files)>MAX_FILES:raise EvidenceError('Maksimal 3 berkas bukti per laporan.')
    saved=[];temporary=None;total=0
    try:
        if files:evidence_root().mkdir(parents=True,exist_ok=True,mode=0o700)
        for file in files:
            file_id=secrets.token_hex(16);temporary=evidence_root()/(file_id+'.part')
            digest=hashlib.sha256();size=0
            with open(temporary,'xb') as target:
                os.chmod(temporary,0o600)
                while True:
                    chunk=file.stream.read(64*1024)
                    if not chunk:break
                    size+=len(chunk);total+=len(chunk)
                    if size>MAX_FILE_BYTES:raise EvidenceError('Ukuran setiap berkas maksimal 20 MB.')
                    if total>MAX_TOTAL_BYTES:raise EvidenceError('Total ukuran bukti maksimal 40 MB.')
                    digest.update(chunk);target.write(chunk)
            if not size:raise EvidenceError('Berkas bukti kosong. Pilih ulang berkasnya.')
            extension,mime=detect_media(temporary,file.filename)
            item={'id':file_id,'extension':extension,'mime':mime,'size':size,'sha256':digest.hexdigest(),
                  'name':(secure_filename(file.filename) or 'bukti')[:150]}
            os.replace(temporary,evidence_path(item));temporary=None;saved.append(item)
        return saved
    except Exception:
        if temporary:temporary.unlink(missing_ok=True)
        remove_evidence(saved)
        raise

"""Transactional storage for public bullying intake."""
import hashlib
import secrets
from psycopg2.extras import Json
from bullying_evidence import store_evidence, remove_evidence

class RateLimited(Exception):
    pass


def save_public_report(data, *, submission_id, ip_hash, site_key, files=()):
    from dashboard.db_access import original_write_cursor
    attachments=[]
    try:
        with original_write_cursor() as cur:
            # Serialize this peer's requests across all gunicorn workers; replays return the same receipt.
            submission_lock=int.from_bytes(hashlib.sha256(submission_id.encode()).digest()[:8],'big',signed=True)
            cur.execute('SELECT pg_advisory_xact_lock(%s)',(submission_lock,))
            lock=int.from_bytes(hashlib.sha256(ip_hash.encode()).digest()[:8],'big',signed=True)
            cur.execute('SELECT pg_advisory_xact_lock(%s)',(lock,))
            cur.execute("SELECT metadata->>'receipt' FROM bullying_reports WHERE metadata->>'source'='public_landingpage' AND metadata->>'submission_id'=%s",(submission_id,))
            existing=cur.fetchone()
            if existing:return existing[0]
            cur.execute("""SELECT count(*) FILTER(WHERE created_at>NOW()-INTERVAL '10 minutes'),count(*)
                FROM bullying_reports WHERE metadata->>'source'='public_landingpage'
                AND metadata->>'ip_hash'=%s AND created_at>NOW()-INTERVAL '1 day'""",(ip_hash,))
            recent,daily=cur.fetchone()
            if recent>=5 or daily>=20:raise RateLimited()
            attachments=store_evidence(files)
            receipt='BL-'+secrets.token_hex(8).upper()
            metadata={k:v for k,v in data.items() if k not in ('description','category')}
            metadata.update(attachments=attachments,source='public_landingpage',receipt=receipt,submission_id=submission_id,ip_hash=ip_hash,site_key=site_key)
            cur.execute("""INSERT INTO bullying_reports(username,description,category,status,priority,severity,metadata)
                VALUES(%s,%s,%s,'pending',%s,%s,%s) RETURNING id""",
                (data['reporter_name'] or 'Anonim',data['description'],data['category'],data['urgent'],'high' if data['urgent'] else None,Json(metadata)))
            report_id=cur.fetchone()[0]
            cur.execute("INSERT INTO bullying_report_events(report_id,event_type,actor,payload) VALUES(%s,'created','Formulir publik',%s)",
                (report_id,Json({'source':'public_landingpage','receipt':receipt})))
    except Exception:
        remove_evidence(attachments)
        raise
    return receipt

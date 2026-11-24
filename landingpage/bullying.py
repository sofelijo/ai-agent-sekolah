"""Anonymous public intake; reports never leave the original database."""
from datetime import date, datetime, timedelta, timezone
import hmac
import hashlib
import secrets
from flask import Blueprint, abort, current_app, redirect, render_template, request, session, url_for

CATEGORIES = {'verbal':'Ucapan / ejekan', 'physical':'Kekerasan fisik', 'social':'Pengucilan / intimidasi', 'cyber':'Perundungan online', 'other':'Lainnya'}
ROLES = {'student':'Siswa', 'parent':'Orang tua / wali', 'teacher':'Guru', 'other':'Lainnya'}
WIB = timezone(timedelta(hours=7))

from bullying_intake import RateLimited
from bullying_evidence import EvidenceError, MAX_REQUEST_BYTES


def validate(form):
    limits={'reporter_name':100,'contact':150,'victim':150,'student_class':60,'offender':200,'location':200,'description':6000}
    data={k:(form.get(k) or '').strip() for k in limits}
    errors=[]
    for k,limit in limits.items():
        if len(data[k])>limit:errors.append(f'Isian terlalu panjang (maksimal {limit} karakter).')
    if len(data['description'])<20:errors.append('Ceritakan kejadian minimal 20 karakter.')
    if len(data['location'])<3:errors.append('Tuliskan lokasi kejadian.')
    data['category']=form.get('category','');data['reporter_role']=form.get('reporter_role','')
    if data['category'] not in CATEGORIES:errors.append('Pilih jenis perundungan.')
    if data['reporter_role'] not in ROLES:errors.append('Pilih hubungan Anda dengan sekolah.')
    data['incident_date']=(form.get('incident_date') or '').strip()
    if data['incident_date']:
        try:
            day=date.fromisoformat(data['incident_date'])
            if day>datetime.now(WIB).date():raise ValueError()
        except ValueError:errors.append('Tanggal kejadian tidak boleh melewati hari ini.')
    data['urgent']=form.get('urgent')=='yes'
    if form.get('consent')!='yes':errors.append('Centang persetujuan pengiriman laporan.')
    return data,errors


def register_bullying(app, *, save_report, fetch_content, resolve_site_key):
    bp=Blueprint('public_bullying',__name__)
    app.config['MAX_CONTENT_LENGTH']=MAX_REQUEST_BYTES
    @bp.after_request
    def private(response):
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','X-Robots-Tag':'noindex, noarchive'})
        return response

    def page(**kwargs):
        return render_template('lapor_bullying.html',content=fetch_content(site_key=resolve_site_key()),
            categories=CATEGORIES,roles=ROLES,today=datetime.now(WIB).date().isoformat(),**kwargs)

    @bp.route('/lapor-bullying',methods=['GET','POST'])
    def report():
        if request.method in ('GET','HEAD'):
            session['bullying_submission']=secrets.token_hex(16)
            session['bullying_issued']=int(datetime.now(timezone.utc).timestamp())
            session.setdefault('bullying_csrf',secrets.token_urlsafe(32))
            return page(values={},errors=[],receipt=None)
        if request.content_length and request.content_length>MAX_REQUEST_BYTES:abort(413)
        if (not request.form.get('csrf_token') or not hmac.compare_digest(request.form['csrf_token'],session.get('bullying_csrf',''))
                or request.form.get('submission_id')!=session.get('bullying_submission')
                or not session.get('bullying_issued') or datetime.now(timezone.utc).timestamp()-session['bullying_issued']>7200):
            return page(values={},errors=['Formulir kedaluwarsa. Muat ulang halaman dan coba lagi.'],receipt=None),400
        if request.form.get('website'):abort(400)
        data,errors=validate(request.form)
        if errors:return page(values=data,errors=errors,receipt=None),422
        # Hash only the trusted peer. Deployment may install ProxyFix for its single nginx proxy.
        peer=request.remote_addr or 'unknown'
        ip_hash=hmac.new(current_app.secret_key.encode(),peer.encode(),hashlib.sha256).hexdigest()
        try:
            receipt=save_report(data,submission_id=session['bullying_submission'],ip_hash=ip_hash,site_key=resolve_site_key(),files=request.files.getlist('evidence'))
        except EvidenceError as exc:
            return page(values=data,errors=[str(exc)],receipt=None),422
        except RateLimited:
            response=current_app.make_response((page(values=data,errors=['Terlalu banyak laporan. Tunggu beberapa saat sebelum mencoba lagi.'],receipt=None),429))
            response.headers['Retry-After']='600';return response
        except Exception:
            current_app.logger.error('Public bullying submission failed; report contents omitted')
            return page(values=data,errors=['Laporan belum tersimpan. Coba kirim lagi beberapa saat.'],receipt=None),503
        session['bullying_receipt']=receipt
        return redirect(url_for('public_bullying.received'),code=303)

    @bp.errorhandler(413)
    def too_large(error):
        return page(values={},errors=['Unggahan terlalu besar. Maksimal 20 MB per berkas dan total 40 MB. Pilih ulang berkas sebelum mengirim.'],receipt=None),413

    @bp.route('/lapor-bullying/terkirim')
    def received():
        receipt=session.get('bullying_receipt')
        if not receipt:return redirect(url_for('public_bullying.report'))
        return page(values={},errors=[],receipt=receipt)
    app.register_blueprint(bp)

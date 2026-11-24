"""Public report storage and restricted dashboard workflow."""
import secrets
from flask import abort, request, session, redirect, url_for, Blueprint, send_file
from .db_access import original_cursor

ENDPOINTS={'bullying_files.evidence','main.bullying_reports','main.bullying_report_detail','main.update_bullying_status','main.bulk_update_bullying_status'}



def init_bullying_dashboard(app):
    bp=Blueprint('bullying_files',__name__)
    @bp.route('/bullying-reports/<int:report_id>/evidence/<file_id>')
    def evidence(report_id,file_id):
        from bullying_evidence import evidence_path
        with original_cursor() as cur:
            cur.execute('SELECT metadata FROM bullying_reports WHERE id=%s',(report_id,));row=cur.fetchone()
        items=(row['metadata'] or {}).get('attachments',[]) if row else []
        item=next((item for item in items if item.get('id')==file_id),None)
        path=evidence_path(item) if item else None
        if not path or not path.is_file():abort(404)
        response=send_file(path,mimetype=item['mime'],as_attachment=True,download_name=item['name'],conditional=True,max_age=0)
        response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff',
            'Content-Security-Policy':"default-src 'none'; sandbox",'Referrer-Policy':'no-referrer'})
        return response
    app.register_blueprint(bp)
    @app.before_request
    def protect_bullying():
        if request.endpoint not in ENDPOINTS:return
        user=session.get('user') or {}
        if not user:return redirect(url_for('auth.login',next=request.path))
        with original_cursor() as cur:
            cur.execute('SELECT role FROM dashboard_users WHERE id=%s',(user.get('id'),));row=cur.fetchone()
        if not row or row['role'] not in ('staff','admin') or user.get('role') not in ('staff','admin'):abort(403)
        if request.method=='POST':
            token=request.headers.get('X-Bullying-CSRF') or request.form.get('bullying_csrf','')
            if not token or not secrets.compare_digest(token,session.get('bullying_admin_csrf','')):abort(400)
    @app.context_processor
    def bullying_context():
        if request.endpoint not in ENDPOINTS:return {}
        session.setdefault('bullying_admin_csrf',secrets.token_urlsafe(32))
        return {'bullying_csrf':session['bullying_admin_csrf']}

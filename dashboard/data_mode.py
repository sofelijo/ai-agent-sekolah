"""Global dashboard display mode; all real writes remain on the original DB."""
import os
import secrets
from flask import Blueprint, abort, flash, g, has_request_context, redirect, render_template, request, session, url_for

data_mode_bp = Blueprint('data_mode', __name__)
SAFE_METHODS = {'GET','HEAD','OPTIONS'}
ORIGINAL_FORMS = {'attendance.kelas','attendance.staff','attendance.laporan_harian',
    'attendance.ekskul_absen','attendance.master_data','attendance.master_staff',
    'attendance.ekskul_master','attendance.ekskul_members','attendance.ekskul_config',
    'library.api_search_students','library.api_check_item',
    'main.bullying_reports','main.bullying_report_detail'}


def global_mode():
    if not has_request_context() or not session.get('user'):
        return 'original'
    if not hasattr(g,'dashboard_global_mode'):
        from .db_access import original_cursor
        with original_cursor() as cur:
            cur.execute('SELECT mode FROM dashboard_data_mode WHERE singleton=TRUE')
            row=cur.fetchone()
        if not row or row['mode'] not in {'original','dummy'}:
            raise RuntimeError('Pengaturan mode data global tidak tersedia')
        g.dashboard_global_mode=row['mode']
    return g.dashboard_global_mode


def dummy_requested():
    if not has_request_context() or not session.get('user'):
        return False
    endpoint=request.endpoint or ''
    if (request.method not in SAFE_METHODS or endpoint.startswith(('auth.','data_mode.'))
            or endpoint in ORIGINAL_FORMS or request.args.get('data_source')=='original'
            or request.headers.get('X-Dashboard-Data-Mode')=='original'):
        return False
    return global_mode()=='dummy'


def can_manage_data_mode():
    if not has_request_context():return False
    if hasattr(g,'can_manage_data_mode'):return g.can_manage_data_mode
    user=session.get('user') or {}; email=(user.get('email') or '').strip().lower()
    allowed={s.strip().lower() for s in os.getenv('DASHBOARD_DATA_MODE_ADMINS','').split(',') if s.strip()}
    permitted=False
    if email in allowed and user.get('role')=='admin' and user.get('id'):
        from .db_access import original_cursor
        with original_cursor() as cur:
            cur.execute('SELECT email,role FROM dashboard_users WHERE id=%s',(user['id'],));row=cur.fetchone()
        permitted=bool(row and row['role']=='admin' and row['email'].strip().lower()==email)
    g.can_manage_data_mode=permitted
    return permitted


def _token():
    if 'data_mode_csrf' not in session:session['data_mode_csrf']=secrets.token_urlsafe(32)
    return session['data_mode_csrf']


@data_mode_bp.route('/settings/data-mode',methods=['GET','POST'])
def settings():
    if not can_manage_data_mode():abort(404)
    if request.method=='POST':
        token=request.form.get('csrf_token','')
        if not token or not secrets.compare_digest(token,session.get('data_mode_csrf','')):abort(400)
        mode=request.form.get('mode')
        if mode not in {'original','dummy'}:abort(400)
        if mode=='dummy':
            from .db_access import demo_pool,_cursor_from_pool
            try:
                with _cursor_from_pool(demo_pool()) as cur:
                    cur.execute("SELECT current_database(),current_setting('transaction_read_only')")
                    row=cur.fetchone()
                    if row[0]!=os.getenv('DASHBOARD_DEMO_DB_NAME') or row[1]!='on':raise RuntimeError('DB dummy tidak terisolasi')
            except Exception:
                from flask import current_app
                current_app.logger.exception('Database dummy tidak tersedia')
                flash('Database dummy belum tersedia. Mode global tidak diubah.','danger')
                return redirect(url_for('data_mode.settings'))
        from .db_access import original_write_cursor
        with original_write_cursor() as cur:
            cur.execute('UPDATE dashboard_data_mode SET mode=%s,updated_by=%s,updated_at=NOW() WHERE singleton=TRUE',
                (mode,session['user']['id']))
        session.pop('dashboard_data_mode',None);session.pop('data_mode_csrf',None)
        flash('Mode dummy aktif untuk semua pengguna.' if mode=='dummy' else 'Data asli aktif untuk semua pengguna.','success')
        return redirect(url_for('main.app_hub'))
    from .db_access import original_cursor
    with original_cursor() as cur:
        cur.execute('SELECT count(*) AS pending FROM dashboard_demo_outbox WHERE synced_at IS NULL');pending=cur.fetchone()['pending']
    return render_template('data_mode.html',data_mode_token=_token(),sync_pending=pending)


def init_data_mode(app):
    app.register_blueprint(data_mode_bp)
    @app.before_request
    def protect_dummy_preview():
        endpoint=request.endpoint or ''
        if request.method not in SAFE_METHODS and endpoint!='data_mode.settings':
            marker=request.headers.get('X-Dashboard-Data-Mode') or request.form.get('_dashboard_data_mode')
            if marker=='dummy':abort(409,description='Data simulasi tidak boleh disimpan ke data asli. Buka formulir data asli atau muat ulang halaman.')
            if session.get('user') and not endpoint.startswith('auth.') and global_mode()=='dummy' and marker!='original':
                abort(409,description='Muat ulang formulir pengisian data asli sebelum menyimpan.')
    @app.after_request
    def private_response(response):
        if session.get('user'):response.headers['Cache-Control']='private, no-store'
        return response
    @app.context_processor
    def mode_context():
        enabled=global_mode()=='dummy'
        params=dict(request.view_args or {});params.update(request.args.to_dict());params['data_source']='original'
        original_url=url_for(request.endpoint,**params) if request.endpoint else '/'
        return dict(can_manage_data_mode=can_manage_data_mode(),dashboard_dummy_mode=dummy_requested(),
            global_dummy_enabled=enabled,original_data_url=original_url,mode_form_source='dummy' if dummy_requested() else 'original')

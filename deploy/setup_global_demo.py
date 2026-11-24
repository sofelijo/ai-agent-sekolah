"""Install global mode + transactional source outbox and least-privilege demo writer."""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values,set_key
import psycopg2
from psycopg2 import sql
from demo_replication import TABLES,MAPPED_TABLES,MASTER_COLUMNS


def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);args=p.parse_args()
    path=args.project/'.env';stat=path.stat();config=dotenv_values(path)
    demo=config['DASHBOARD_DEMO_DB_NAME'];original=config['DB_NAME']
    if demo==original:raise RuntimeError('Separate databases required')
    c=psycopg2.connect(dbname=original,user=config['DB_USER'],password=config['DB_PASS'],host=config['DB_HOST'],port=config['DB_PORT'])
    def postgres(statement,database):
        result=subprocess.run(['sudo','-u','postgres','psql','-X','-v','ON_ERROR_STOP=1','-d',database],
            cwd='/tmp',input='BEGIN;\n'+statement+'\nCOMMIT;',text=True,capture_output=True)
        if result.returncode:raise RuntimeError('Global demo setup failed (SQL not printed to protect credentials)')
    ident=lambda value:sql.Identifier(value).as_string(c)
    literal=lambda value:sql.Literal(value).as_string(c)
    writer=config.get('DASHBOARD_DEMO_WRITER_USER') or 'aska_dashboard_demo_writer'
    password=config.get('DASHBOARD_DEMO_WRITER_PASS') or secrets.token_hex(32)
    postgres("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname="+literal(writer)+") THEN CREATE ROLE "+ident(writer)+" LOGIN PASSWORD "+literal(password)+" NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; END IF; END $$;",'postgres')
    for key,value in {'DASHBOARD_DEMO_WRITER_USER':writer,'DASHBOARD_DEMO_WRITER_PASS':password}.items():set_key(str(path),key,value)
    os.chown(path,stat.st_uid,stat.st_gid);os.chmod(path,stat.st_mode&0o777)
    target=[]
    for table in MAPPED_TABLES-{'extracurricular_coaches'}:
        target.append('ALTER TABLE public.'+ident(table)+' ADD COLUMN IF NOT EXISTS source_record_id BIGINT UNIQUE;')
    target+=['GRANT USAGE ON SCHEMA public TO '+ident(writer)+';',
        'GRANT SELECT,INSERT,UPDATE,DELETE ON '+','.join('public.'+ident(t) for t in TABLES)+' TO '+ident(writer)+';',
        'GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO '+ident(writer)+';']
    postgres('\n'.join(target),demo)
    source="""CREATE TABLE IF NOT EXISTS public.dashboard_data_mode(
        singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),mode TEXT NOT NULL CHECK(mode IN ('original','dummy')),
        updated_by INTEGER REFERENCES public.dashboard_users(id),updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
        INSERT INTO public.dashboard_data_mode(singleton,mode) VALUES(TRUE,'original') ON CONFLICT DO NOTHING;
        CREATE TABLE IF NOT EXISTS public.dashboard_demo_outbox(
        id BIGSERIAL PRIMARY KEY,table_name TEXT NOT NULL,row_key JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        synced_at TIMESTAMPTZ,last_attempt_at TIMESTAMPTZ,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT);
        CREATE INDEX IF NOT EXISTS dashboard_demo_pending ON public.dashboard_demo_outbox(id) WHERE synced_at IS NULL;
        CREATE OR REPLACE FUNCTION public.capture_dashboard_demo_change() RETURNS trigger LANGUAGE plpgsql
        SECURITY DEFINER SET search_path=pg_catalog,public AS $$ DECLARE r JSONB; BEGIN
        r=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
        INSERT INTO public.dashboard_demo_outbox(table_name,row_key) VALUES(TG_TABLE_NAME,
        jsonb_strip_nulls(jsonb_build_object('id',r->'id','attendance_date',r->'attendance_date',
        'student_id',r->'student_id','teacher_id',r->'teacher_id','extracurricular_id',r->'extracurricular_id',
        'coach_user_id',r->'coach_user_id','book_item_id',r->'book_item_id')));
        IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW; END $$;
        """
    for table in TABLES:
        source+='DROP TRIGGER IF EXISTS capture_demo_change ON public.'+ident(table)+';\n'
        source+='CREATE TRIGGER capture_demo_change AFTER INSERT OR UPDATE OR DELETE ON public.'+ident(table)+' FOR EACH ROW EXECUTE FUNCTION public.capture_dashboard_demo_change();\n'
    source+='GRANT SELECT,UPDATE ON public.dashboard_data_mode TO '+ident(config['DB_USER'])+';\n'
    source+='GRANT SELECT,UPDATE,INSERT ON public.dashboard_demo_outbox TO '+ident(config['DB_USER'])+';\n'
    source+='GRANT USAGE,SELECT ON SEQUENCE public.dashboard_demo_outbox_id_seq TO '+ident(config['DB_USER'])+';\n'
    # Refresh only reference masters, not old original transaction history.
    for table in ('dashboard_users','student_violation_categories','student_violation_types','student_point_thresholds'):
        source+='INSERT INTO public.dashboard_demo_outbox(table_name,row_key) SELECT '+literal(table)+",jsonb_build_object('id',id) FROM public."+ident(table)+';\n'
    postgres(source,original)
    unit=f'''[Unit]
Description=Original-to-demo durable synchronization
After=network.target postgresql.service
[Service]
WorkingDirectory={args.project}
EnvironmentFile={args.project}/.env
Environment=PYTHONUNBUFFERED=1
ExecStart={args.project}/venv/bin/python {args.project}/deploy/sync_demo.py --project {args.project}
User=www-data
Group=www-data
Restart=always
RestartSec=3
MemoryMax=128M
[Install]
WantedBy=multi-user.target
'''
    Path('/etc/systemd/system/aska-demo-sync.service').write_text(unit)
    c.close();print('Global setting, durable outbox and restricted demo writer installed.')


if __name__=='__main__':main()

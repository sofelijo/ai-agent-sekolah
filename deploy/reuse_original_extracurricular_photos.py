"""Reuse existing original photo files on matching synthetic sessions, without copying original attendance."""
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from demo_replication import connect


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,required=True)
    p.add_argument('--start',type=date.fromisoformat,required=True)
    p.add_argument('--end',type=date.fromisoformat,required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--backup-dir',type=Path);p.add_argument('--report',type=Path)
    args=p.parse_args();config=dotenv_values(args.project/'.env')
    if config['DB_NAME']==config['DASHBOARD_DEMO_DB_NAME']:raise RuntimeError('Separate dummy DB required')
    source=connect(config);source.set_session(readonly=True)
    try:
        with source.cursor() as cur:
            # Legacy combined Pramuka (id 1) cannot safely be classified as Siaga/Penggalang.
            cur.execute("""SELECT DISTINCT ON (extracurricular_id,attendance_date)
                extracurricular_id,attendance_date,photo_path FROM extracurricular_attendance_records
                WHERE attendance_date BETWEEN %s AND %s AND extracurricular_id<>1 AND NULLIF(trim(photo_path),'') IS NOT NULL
                ORDER BY extracurricular_id,attendance_date,updated_at DESC,id DESC""",(args.start,args.end))
            rows=cur.fetchall()
    finally:source.close()
    entries=[];static=(args.project/'dashboard/static').resolve()
    for aid,day,path in rows:
        file=(static/path).resolve()
        if static not in file.parents or not file.is_file():raise RuntimeError('Original photo file is not available')
        entries.append({'activity_id':aid,'date':day.isoformat(),'photo_path':path,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
    destination=connect(config,True)
    try:
        with destination.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(7831262027)')
            for entry in entries:
                cur.execute("""SELECT count(*),count(*) FILTER(WHERE source_record_id IS NULL),
                    array_agg(DISTINCT photo_path) FILTER(WHERE NULLIF(trim(photo_path),'') IS NOT NULL)
                    FROM extracurricular_attendance_records WHERE extracurricular_id=%s AND attendance_date=%s""",(entry['activity_id'],entry['date']))
                total,synthetic,existing=cur.fetchone()
                entry['status']='ready' if synthetic and not existing else ('existing_photo_preserved' if existing else 'no_synthetic_session')
                entry['rows']=synthetic
            if args.apply:
                if not args.backup_dir:raise ValueError('Private --backup-dir required')
                args.backup_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
                with open(args.backup_dir/'dummy-before-original-photo-links.dump','xb') as out:
                    os.chmod(out.name,0o600)
                    subprocess.run(['sudo','-u','postgres','pg_dump','-Fc','-d',config['DASHBOARD_DEMO_DB_NAME'],'-t','public.extracurricular_attendance_records'],cwd='/tmp',stdout=out,check=True)
                for entry in entries:
                    if entry['status']!='ready':continue
                    cur.execute("""UPDATE extracurricular_attendance_records SET photo_path=%s
                        WHERE extracurricular_id=%s AND attendance_date=%s AND source_record_id IS NULL AND NULLIF(trim(photo_path),'') IS NULL""",
                        (entry['photo_path'],entry['activity_id'],entry['date']))
                    if cur.rowcount!=entry['rows']:raise RuntimeError('Session changed during linking')
                    entry['status']='linked'
                destination.commit()
            else:destination.rollback()
    except Exception:destination.rollback();raise
    finally:destination.close()
    if args.report:args.report.write_text(json.dumps({'target':'dummy_only','original_db':'read_only','sessions':entries},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'photos':len(entries),'summary':{s:sum(e['status']==s for e in entries) for s in sorted(set(e['status'] for e in entries))}}))

if __name__=='__main__':main()

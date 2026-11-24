"""Import dated, already-cropped photos into synthetic extracurricular rows only.

Dry-run by default. Never writes to the original database or overwrites existing
session photos, real mirrored attendance, attendance status, timestamps or GPS.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from PIL import Image,ImageOps
from demo_replication import connect

ACTIVITIES={'pramuka-siaga':1,'pencak-silat':2,'tari-tradisional':3,'futsal':4,'marawis':5,'pramuka-penggalang':7}
EXTENSIONS={'.jpg','.jpeg','.png','.webp'}


def inventory(folder):
    entries=[]
    for group,aid in ACTIVITIES.items():
        for file in sorted((folder/group).glob('*/*')):
            if not file.is_file() or file.suffix.lower() not in EXTENSIONS:continue
            day=datetime.strptime(file.parent.name,'%d-%m-%Y').date()
            with Image.open(file) as raw:raw.verify()
            with Image.open(file) as raw:
                image=ImageOps.exif_transpose(raw)
                if image.width*4!=image.height*3:raise ValueError(f'Photo must already be 3:4: {file.relative_to(folder)}')
                size=image.size
            digest=hashlib.sha256(file.read_bytes()).hexdigest()
            entries.append({'activity_id':aid,'date':day.isoformat(),'file':str(file.relative_to(folder)),
                'sha256':digest,'width':size[0],'height':size[1],
                'photo_path':f'uploads/ekskul/{aid}/{day.isoformat()}/import_{digest[:24]}{file.suffix.lower()}'})
    keys=[(e['activity_id'],e['date']) for e in entries]
    if len(keys)!=len(set(keys)):raise ValueError('Multiple photos for one date require selecting the main photo first')
    return entries


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--photos',type=Path,required=True)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup-dir',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();config=dotenv_values(args.project/'.env')
    if config['DB_NAME']==config['DASHBOARD_DEMO_DB_NAME']:raise RuntimeError('Separate dummy database required')
    entries=inventory(args.photos);db=connect(config,True);created=[]
    try:
        with db.cursor() as cur:
            # Refuse silently competing imports; this lock does not block teachers.
            cur.execute('SELECT pg_advisory_xact_lock(7831262027)')
            for entry in entries:
                cur.execute("""SELECT count(*),count(*) FILTER(WHERE source_record_id IS NULL),
                    array_agg(DISTINCT photo_path) FILTER(WHERE NULLIF(trim(photo_path),'') IS NOT NULL)
                    FROM extracurricular_attendance_records WHERE extracurricular_id=%s AND attendance_date=%s""",
                    (entry['activity_id'],entry['date']))
                total,synthetic,existing=cur.fetchone()
                if not total:raise RuntimeError(f"No session for {entry['activity_id']} on {entry['date']}")
                if existing:
                    entry['status']='already_imported' if existing==[entry['photo_path']] else 'existing_photo_preserved'
                elif not synthetic:entry['status']='real_records_preserved'
                else:entry['status']='ready';entry['rows']=synthetic
            if args.apply:
                if not args.backup_dir:raise ValueError('--backup-dir required when applying')
                args.backup_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
                dump=args.backup_dir/'dummy-extracurricular-before.dump'
                if dump.exists():raise RuntimeError('Backup file exists; choose a new private backup directory')
                with open(dump,'xb') as out:
                    os.chmod(dump,0o600)
                    subprocess.run(['sudo','-u','postgres','pg_dump','-Fc','-d',config['DASHBOARD_DEMO_DB_NAME'],
                        '-t','public.extracurricular_attendance_records'],cwd='/tmp',stdout=out,check=True)
                for entry in entries:
                    if entry['status']!='ready':continue
                    source=args.photos/entry['file'];target=args.project/'dashboard/static'/entry['photo_path']
                    if target.exists():
                        if hashlib.sha256(target.read_bytes()).hexdigest()!=entry['sha256']:raise RuntimeError('Existing file checksum mismatch')
                    else:
                        target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_suffix(target.suffix+'.part')
                        shutil.copyfile(source,temporary);os.chmod(temporary,0o644);os.replace(temporary,target);created.append(target)
                    cur.execute("""UPDATE extracurricular_attendance_records SET photo_path=%s
                        WHERE extracurricular_id=%s AND attendance_date=%s AND source_record_id IS NULL
                        AND NULLIF(trim(photo_path),'') IS NULL""",(entry['photo_path'],entry['activity_id'],entry['date']))
                    if cur.rowcount!=entry['rows']:raise RuntimeError('Session changed while importing; transaction rolled back')
                    entry['status']='imported'
                db.commit()
            else:db.rollback()
    except Exception:
        db.rollback()
        for file in created:file.unlink(missing_ok=True)
        raise
    finally:db.close()
    report={'applied':args.apply,'target':'dummy_only','ratio':'3:4','sessions':entries}
    if args.report:args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    counts={status:sum(e['status']==status for e in entries) for status in sorted(set(e['status'] for e in entries))}
    print(json.dumps({'photos':len(entries),'summary':counts},ensure_ascii=False))

if __name__=='__main__':main()

-- Synthetic fixtures only. Run against a NEW, EMPTY demo database, never production.
BEGIN;
INSERT INTO dashboard_users (id,email,full_name,password_hash,role) VALUES
 (27,'admin@example.invalid','Admin Demo','!login-disabled','admin'),
 (28,'guru@example.invalid','Guru Demo','!login-disabled','staff');
INSERT INTO school_classes (id,name,academic_year) VALUES
 (1,'1A Demo','2026/2027'),(2,'2A Demo','2026/2027'),(3,'6A Demo','2026/2027'),
 (4,'3A Demo','2026/2027'),(5,'4A Demo','2026/2027'),(6,'5A Demo','2026/2027');
INSERT INTO students (id,class_id,full_name,student_number,nisn,gender,sequence)
 SELECT n,1+((n-1)%3)+CASE WHEN n>9 THEN 3 ELSE 0 END,'Siswa Demo '||n,'DEMO-'||n,'990000'||lpad(n::text,4,'0'),
 CASE WHEN n%2=0 THEN 'P' ELSE 'L' END,n FROM generate_series(1,18) n;
INSERT INTO attendance_records (attendance_date,student_id,class_id,teacher_id,status)
 SELECT CURRENT_DATE-days,s.id,s.class_id,28,
 CASE WHEN (s.id+days)%9=0 THEN 'sakit' WHEN (s.id+days)%7=0 THEN 'izin' ELSE 'masuk' END
 FROM students s CROSS JOIN generate_series(0,6) days;
INSERT INTO teacher_attendance_records (attendance_date,teacher_id,status,recorded_by)
 SELECT CURRENT_DATE-days,28,'masuk',27 FROM generate_series(0,6) days;
INSERT INTO extracurriculars (id,name,coach_name,coach_user_id,schedule_day,location,created_by)
 VALUES (1,'Pramuka Demo','Guru Demo',28,'Jumat','Lapangan Demo',27);
INSERT INTO extracurricular_coaches (extracurricular_id,coach_user_id,assigned_by) VALUES (1,28,27);
INSERT INTO extracurricular_members (extracurricular_id,student_id)
 SELECT 1,id FROM students WHERE id<=8;
INSERT INTO extracurricular_attendance_records (attendance_date,extracurricular_id,student_id,status,recorded_by,material)
 SELECT CURRENT_DATE,1,id,'masuk',28,'Latihan simpul demo' FROM students WHERE id<=8;
INSERT INTO books (id,title,author,publisher,year,code,stock,location) VALUES
 (1,'Petualangan di Taman Demo','Penulis Demo','Penerbit Demo',2026,'DEMO-001',3,'Rak A'),
 (2,'Mengenal Sains Demo','Penulis Demo','Penerbit Demo',2026,'DEMO-002',3,'Rak B'),
 (3,'Cerita Persahabatan Demo','Penulis Demo','Penerbit Demo',2026,'DEMO-003',3,'Rak A');
INSERT INTO book_items (id,book_id,qr_code,status)
 SELECT n,1+((n-1)/3),'DEMO-ITEM-'||n,CASE WHEN n IN (1,4) THEN 'borrowed' ELSE 'available' END
 FROM generate_series(1,9) n;
INSERT INTO borrowing_records (student_id,book_id,book_item_id,borrow_date,due_date,status,recorded_by)
 VALUES (1,1,1,CURRENT_DATE-2,CURRENT_DATE+5,'borrowed',27),
 (2,2,4,CURRENT_DATE-10,CURRENT_DATE-3,'borrowed',27);
INSERT INTO borrowing_records (student_id,book_id,book_item_id,borrow_date,due_date,return_date,status,recorded_by,returned_by)
 VALUES (3,3,7,CURRENT_DATE-8,CURRENT_DATE-1,CURRENT_DATE-2,'returned',27,28);
INSERT INTO web_users (id,email,full_name,auth_provider)
 VALUES (1,'siswa@example.invalid','Siswa Demo','gmail');
INSERT INTO telegram_users (telegram_user_id,username,last_message_preview)
 VALUES (990000001,'siswa_demo','Apa kegiatan sekolah hari ini?');
INSERT INTO chat_logs (id,user_id,username,text,role,topic,channel,created_at)
 SELECT n,990000001,'siswa_demo',
 CASE WHEN n%2=1 THEN 'Apa kegiatan sekolah hari ini?' ELSE 'Ada kegiatan membaca bersama di perpustakaan demo.' END,
 CASE WHEN n%2=1 THEN 'user' ELSE 'assistant' END,'sekolah','telegram',NOW()-(n||' hours')::interval
 FROM generate_series(1,20) n;
INSERT INTO chat_feedback (chat_log_id,user_id,username,feedback_type)
 VALUES (2,990000001,'siswa_demo','like');
INSERT INTO bullying_reports (chat_log_id,user_id,username,description,status)
 VALUES (1,990000001,'siswa_demo','Contoh laporan rekaan untuk demonstrasi.','pending');
INSERT INTO psych_reports (chat_log_id,user_id,username,message,summary,severity,status)
 VALUES (3,990000001,'siswa_demo','Contoh pesan rekaan untuk demonstrasi.','Contoh ringkasan demo','low','open');
INSERT INTO corruption_reports (ticket_id,user_id,status,involved,location,chronology)
 VALUES ('DEMO-001',990000001,'open','Tokoh Demo','Lokasi Demo','Contoh laporan rekaan untuk demonstrasi.');
INSERT INTO twitter_worker_logs (level,message) VALUES ('info','Contoh aktivitas worker demo.');
INSERT INTO notifications (category,title,message,status)
 VALUES ('demo','Notifikasi Demo','Ini hanya data contoh.','unread');
INSERT INTO landingpage_teachers (site_key,name,role,is_active)
 VALUES ('default','Guru Demo','Guru Kelas',TRUE);
INSERT INTO landingpage_settings (site_key,data) VALUES ('default',
 '{"site_name":"Sekolah Demo","city":"Kota Demo","hero":{"title":"Sekolah Demo","subtitle":"Kota Demo","description":"Contoh profil rekaan.","background_image":"","primary_cta":{"label":"Demo","url":"#"},"social_links":[]},"documentation":{"title":"Dokumentasi Demo","videos":[]},"profile":{"title":"Profil Demo","leaders":[{"role":"Kepala Sekolah","name":"Kepala Sekolah Demo","education":"Pendidikan Demo","image":""}],"vision_title":"Visi Demo","vision":"Belajar bersama di sekolah demo.","missions":["Contoh misi sekolah demo."]},"activities":{"title":"Kegiatan Demo","items":[]},"extracurricular":{"title":"Ekstrakurikuler Demo","items":[{"title":"Pramuka Demo","description":"Latihan demo.","image":""}]},"footer":{"text":"Sekolah Demo"},"seo":{"meta_title":"Sekolah Demo","meta_description":"Profil rekaan","meta_keywords":"demo","og_title":"Sekolah Demo","og_description":"Profil rekaan","og_image":"","twitter_card":"summary","favicon":""}}');
INSERT INTO landingpage_graduations (site_key,nisn,student_name,class_name,graduation_year,status)
 VALUES ('default','9900000001','Siswa Demo Lulus','6A Demo',2026,'lulus');
INSERT INTO tka_mata_pelajaran (id,name,grade_level) VALUES (1,'Matematika Demo','sd6');
INSERT INTO tka_tests (id,name,grade_level,duration_minutes) VALUES (1,'Latihan TKA Demo','sd6',30);
INSERT INTO tka_test_subjects (id,test_id,mapel_id,question_count_target) VALUES (1,1,1,1);
INSERT INTO tka_questions (id,mapel_id,test_id,test_subject_id,topic,difficulty,prompt,options,correct_key,explanation,created_by)
 VALUES (1,1,1,1,'Penjumlahan','easy','Berapakah 2 + 3?',
 '[{"key":"A","text":"4"},{"key":"B","text":"5"},{"key":"C","text":"6"},{"key":"D","text":"7"}]',
 'B','2 + 3 = 5.',27);
INSERT INTO tka_quiz_attempts (mapel_id,test_id,web_user_id,status,time_limit_minutes,question_count,correct_count,score,completed_at)
 VALUES (1,1,1,'completed',30,1,1,100,NOW());
DO $$ BEGIN
 IF to_regclass('public.student_point_records') IS NOT NULL THEN
  INSERT INTO student_violation_categories (name,description) VALUES ('Kedisiplinan Demo','Kategori rekaan');
  INSERT INTO student_violation_types (id,code,name,category,points)
   VALUES (1,'DEMO-01','Terlambat Demo','Kedisiplinan Demo',5);
  INSERT INTO student_point_thresholds (min_points,label,color,recommended_action)
   VALUES (10,'Pembinaan Demo','warning','Contoh pembinaan rekaan');
  INSERT INTO student_point_records (student_id,violation_type_id,violation_code,violation_name,category,points,occurred_at,recorded_by)
   VALUES (1,1,'DEMO-01','Terlambat Demo','Kedisiplinan Demo',5,NOW(),27);
 END IF;
END $$;
-- Keep sequences ahead of explicit synthetic IDs.
DO $$ DECLARE r RECORD; seq TEXT; maximum BIGINT; BEGIN
 FOR r IN SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='id' LOOP
  seq := pg_get_serial_sequence(format('public.%I',r.table_name),'id');
  IF seq IS NOT NULL THEN
   EXECUTE format('SELECT MAX(id) FROM public.%I',r.table_name) INTO maximum;
   IF maximum IS NOT NULL THEN PERFORM setval(seq,maximum); END IF;
  END IF;
 END LOOP;
END $$;
COMMIT;

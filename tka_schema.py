"""Shared SQL helpers to provision Latihan TKA tables."""

from __future__ import annotations

TKA_DEFAULT_MIX = """'{"easy":10,"medium":5,"hard":5}'::jsonb"""


def ensure_tka_schema(cursor) -> None:
    """Create core Latihan TKA tables and indexes if they do not exist."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_subjects (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            question_count INTEGER NOT NULL DEFAULT 20,
            time_limit_minutes INTEGER NOT NULL DEFAULT 15,
            difficulty_mix JSONB NOT NULL DEFAULT """ + TKA_DEFAULT_MIX + """,
            difficulty_presets JSONB,
            default_preset TEXT,
            question_revision INTEGER NOT NULL DEFAULT 1,
            grade_level TEXT NOT NULL DEFAULT 'sd6',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_subjects
        ADD COLUMN IF NOT EXISTS difficulty_presets JSONB;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_subjects
        ADD COLUMN IF NOT EXISTS default_preset TEXT;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_subjects
        ADD COLUMN IF NOT EXISTS question_revision INTEGER NOT NULL DEFAULT 1;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_subjects
        ADD COLUMN IF NOT EXISTS grade_level TEXT NOT NULL DEFAULT 'sd6';
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_stimulus (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER NOT NULL REFERENCES tka_subjects(id) ON DELETE CASCADE,
            title TEXT,
            type TEXT NOT NULL DEFAULT 'text',
            narrative TEXT,
            image_url TEXT,
            image_prompt TEXT,
            ai_prompt TEXT,
            metadata JSONB,
            created_by INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_stimulus_subject
        ON tka_stimulus (subject_id);
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_questions (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER NOT NULL REFERENCES tka_subjects(id) ON DELETE CASCADE,
            stimulus_id INTEGER REFERENCES tka_stimulus(id) ON DELETE SET NULL,
            topic TEXT,
            difficulty TEXT NOT NULL,
            prompt TEXT NOT NULL,
            options JSONB NOT NULL,
            correct_key TEXT NOT NULL,
            explanation TEXT,
            created_by INTEGER,
            source TEXT,
            ai_prompt TEXT,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT tka_questions_difficulty_check CHECK (difficulty IN ('easy','medium','hard'))
        );
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_questions
        ADD COLUMN IF NOT EXISTS stimulus_id INTEGER REFERENCES tka_stimulus(id) ON DELETE SET NULL;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_questions
        ADD COLUMN IF NOT EXISTS test_id INTEGER REFERENCES tka_tests(id) ON DELETE SET NULL;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_questions
        ADD COLUMN IF NOT EXISTS test_subject_id INTEGER REFERENCES tka_test_subjects(id) ON DELETE SET NULL;
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_questions_subject
        ON tka_questions (subject_id, difficulty);
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_questions_stimulus
        ON tka_questions (stimulus_id);
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_questions
        ADD COLUMN IF NOT EXISTS answer_format TEXT NOT NULL DEFAULT 'multiple_choice';
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_questions_answer_format
        ON tka_questions (answer_format);
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_quiz_attempts (
            id SERIAL PRIMARY KEY,
            subject_id INTEGER NOT NULL REFERENCES tka_subjects(id) ON DELETE CASCADE,
            web_user_id BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_progress',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            time_limit_minutes INTEGER NOT NULL,
            question_count INTEGER NOT NULL,
            correct_count INTEGER,
            score INTEGER,
            duration_seconds INTEGER,
            difficulty_breakdown JSONB,
            analysis_prompt TEXT,
            analysis_sent_at TIMESTAMPTZ,
            metadata JSONB,
            revision_snapshot INTEGER NOT NULL DEFAULT 1,
            is_repeat BOOLEAN NOT NULL DEFAULT FALSE,
            repeat_iteration INTEGER NOT NULL DEFAULT 0,
            difficulty_preset TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT tka_attempts_status_check CHECK (
                status IN ('in_progress', 'completed', 'expired', 'cancelled')
            )
        );
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_quiz_attempts
        ADD COLUMN IF NOT EXISTS revision_snapshot INTEGER NOT NULL DEFAULT 1;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_quiz_attempts
        ADD COLUMN IF NOT EXISTS is_repeat BOOLEAN NOT NULL DEFAULT FALSE;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_quiz_attempts
        ADD COLUMN IF NOT EXISTS repeat_iteration INTEGER NOT NULL DEFAULT 0;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_quiz_attempts
        ADD COLUMN IF NOT EXISTS difficulty_preset TEXT;
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_attempts_user
        ON tka_quiz_attempts (web_user_id, status);
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_attempt_questions (
            id SERIAL PRIMARY KEY,
            attempt_id INTEGER NOT NULL REFERENCES tka_quiz_attempts(id) ON DELETE CASCADE,
            question_id INTEGER REFERENCES tka_questions(id) ON DELETE SET NULL,
            prompt TEXT NOT NULL,
            options JSONB NOT NULL,
            correct_key TEXT NOT NULL,
            selected_key TEXT,
            is_correct BOOLEAN,
            difficulty TEXT NOT NULL,
            topic TEXT,
            explanation TEXT,
            metadata JSONB,
            order_index INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_attempt_questions_attempt
        ON tka_attempt_questions (attempt_id, order_index);
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_attempt_questions
        ADD COLUMN IF NOT EXISTS answer_format TEXT NOT NULL DEFAULT 'multiple_choice';
        """
    )

    # Tes berisi banyak mapel + format + topik
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_tests (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            grade_level TEXT,
            duration_minutes INTEGER NOT NULL DEFAULT 120,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            metadata JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_tests
        ALTER COLUMN grade_level DROP NOT NULL;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_tests
        ALTER COLUMN grade_level DROP DEFAULT;
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_mata_pelajaran (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            grade_level TEXT NOT NULL DEFAULT 'sd6',
            description TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_mata_pelajaran
        DROP COLUMN IF EXISTS subject_id;
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_questions
        ADD COLUMN IF NOT EXISTS mapel_id INTEGER REFERENCES tka_mata_pelajaran(id) ON DELETE SET NULL;
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_questions_mapel
        ON tka_questions (mapel_id);
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_test_question_formats (
            id SERIAL PRIMARY KEY,
            test_subject_id INTEGER NOT NULL REFERENCES tka_test_subjects(id) ON DELETE CASCADE,
            question_type TEXT NOT NULL,
            question_count_target INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT tka_test_question_formats_type_check CHECK (question_type IN ('multiple_choice','true_false'))
        );
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_test_question_formats_subject
        ON tka_test_question_formats (test_subject_id);
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_test_topics (
            id SERIAL PRIMARY KEY,
            test_subject_id INTEGER NOT NULL REFERENCES tka_test_subjects(id) ON DELETE CASCADE,
            topic TEXT NOT NULL,
            question_count_target INTEGER NOT NULL DEFAULT 0,
            order_index INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_test_topics_subject
        ON tka_test_topics (test_subject_id, order_index);
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_test_subjects (
            id SERIAL PRIMARY KEY,
            test_id INTEGER NOT NULL REFERENCES tka_tests(id) ON DELETE CASCADE,
            mapel_id INTEGER REFERENCES tka_mata_pelajaran(id) ON DELETE SET NULL,
            question_count_target INTEGER NOT NULL DEFAULT 0,
            order_index INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_test_subjects
        DROP COLUMN IF EXISTS subject_id;
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tka_test_subjects_test
        ON tka_test_subjects (test_id, order_index);
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_mapel_formats (
            id SERIAL PRIMARY KEY,
            mapel_id INTEGER NOT NULL REFERENCES tka_mata_pelajaran(id) ON DELETE CASCADE,
            question_type TEXT NOT NULL,
            question_count INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT tka_mapel_formats_type_check CHECK (question_type IN ('multiple_choice','true_false'))
        );
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tka_mapel_topics (
            id SERIAL PRIMARY KEY,
            mapel_id INTEGER NOT NULL REFERENCES tka_mata_pelajaran(id) ON DELETE CASCADE,
            topic TEXT NOT NULL,
            question_count INTEGER NOT NULL DEFAULT 0,
            order_index INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    cursor.execute(
        """
        ALTER TABLE tka_test_subjects
        ADD COLUMN IF NOT EXISTS mapel_id INTEGER REFERENCES tka_mata_pelajaran(id) ON DELETE SET NULL;
        """
    )

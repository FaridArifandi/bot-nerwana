import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cleaning.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabel Utama: kasus_nerwana
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kasus_nerwana (
        assignment_id TEXT NOT NULL,
        nama_usaha TEXT NOT NULL,
        kabkota TEXT DEFAULT '1175',
        kategori TEXT DEFAULT 'A',
        kbli TEXT,
        deskripsi_kbli TEXT,
        link_fasih TEXT,
        pbj REAL,
        prod REAL,
        ops REAL,
        beli REAL,
        nonops REAL,
        lain REAL,
        output REAL,
        ntb REAL,
        rasio REAL,
        filter_spesifik TEXT,
        tindak_lanjut TEXT,
        tindak_lanjut_oleh TEXT,
        data_kunci TEXT,
        status TEXT DEFAULT 'PENDING',
        alasan_review TEXT,
        nilai_baru_pbj REAL,
        nilai_baru_prod REAL,
        nilai_baru_ops REAL,
        rasio_baru REAL,
        skor_usulan REAL,
        alasan_usulan TEXT,
        kode_catatan TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (assignment_id, nama_usaha)
    )
    """)

    # Tabel Audit Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assignment_id TEXT,
        nama_usaha TEXT,
        action TEXT,
        nilai_lama TEXT,
        nilai_baru TEXT,
        kode_catatan TEXT,
        status_sebelumnya TEXT,
        status_baru TEXT,
        pesan TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()
    print(f"[DATABASE] Database initialized at: {DB_PATH}")

def upsert_kasus(row_data):
    conn = get_connection()
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute("""
    INSERT INTO kasus_nerwana (
        assignment_id, nama_usaha, kabkota, kategori, kbli, deskripsi_kbli, link_fasih,
        pbj, prod, ops, beli, nonops, lain, output, ntb, rasio,
        filter_spesifik, tindak_lanjut, tindak_lanjut_oleh, data_kunci, updated_at
    ) VALUES (
        :assignment_id, :nama_usaha, :kabkota, :kategori, :kbli, :deskripsi_kbli, :link_fasih,
        :pbj, :prod, :ops, :beli, :nonops, :lain, :output, :ntb, :rasio,
        :filter_spesifik, :tindak_lanjut, :tindak_lanjut_oleh, :data_kunci, :updated_at
    )
    ON CONFLICT(assignment_id, nama_usaha) DO UPDATE SET
        kabkota = excluded.kabkota,
        kategori = excluded.kategori,
        kbli = excluded.kbli,
        deskripsi_kbli = excluded.deskripsi_kbli,
        link_fasih = excluded.link_fasih,
        pbj = excluded.pbj,
        prod = excluded.prod,
        ops = excluded.ops,
        beli = excluded.beli,
        nonops = excluded.nonops,
        lain = excluded.lain,
        output = excluded.output,
        ntb = excluded.ntb,
        rasio = excluded.rasio,
        filter_spesifik = CASE 
            WHEN kasus_nerwana.filter_spesifik IS NULL OR kasus_nerwana.filter_spesifik = '' THEN excluded.filter_spesifik
            WHEN instr(kasus_nerwana.filter_spesifik, excluded.filter_spesifik) > 0 THEN kasus_nerwana.filter_spesifik
            ELSE kasus_nerwana.filter_spesifik || ',' || excluded.filter_spesifik
        END,
        tindak_lanjut = excluded.tindak_lanjut,
        tindak_lanjut_oleh = excluded.tindak_lanjut_oleh,
        data_kunci = excluded.data_kunci,
        updated_at = excluded.updated_at
    """, {**row_data, 'updated_at': now})
    
    conn.commit()
    conn.close()

def log_audit(assignment_id, nama_usaha, action, nilai_lama=None, nilai_baru=None, kode_catatan=None, status_sebelumnya=None, status_baru=None, pesan=None):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO audit_log (
        assignment_id, nama_usaha, action, nilai_lama, nilai_baru, kode_catatan, status_sebelumnya, status_baru, pesan
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        assignment_id,
        nama_usaha,
        action,
        json.dumps(nilai_lama) if isinstance(nilai_lama, (dict, list)) else str(nilai_lama or ''),
        json.dumps(nilai_baru) if isinstance(nilai_baru, (dict, list)) else str(nilai_baru or ''),
        kode_catatan,
        status_sebelumnya,
        status_baru,
        pesan
    ))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()

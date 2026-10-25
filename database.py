import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_cleaning.db")

# Kolom-kolom baru yang ditambahkan di Fase 0 (migrasi aman, nullable)
_MIGRATION_COLUMNS = [
    ("kasus_nerwana", "blok", "TEXT"),
    ("kasus_nerwana", "nilai_lama_fasih", "TEXT"),       # JSON: {pbj, prod, ops, beli}
    ("kasus_nerwana", "nilai_baru_fasih", "TEXT"),       # JSON: {pbj, prod, ops, beli}
    ("kasus_nerwana", "alasan_skip", "TEXT"),
    ("kasus_nerwana", "remark_terverifikasi", "INTEGER DEFAULT 0"),
    ("kasus_nerwana", "evaluasi_at", "TIMESTAMP"),
]

def _safe_migrate(conn):
    """Menambahkan kolom baru ke tabel yang sudah ada secara aman.
    ALTER TABLE ... ADD COLUMN akan diabaikan jika kolom sudah ada."""
    for table, col, col_type in _MIGRATION_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            # Kolom sudah ada, abaikan
            pass
    conn.commit()

def get_connection():
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _safe_migrate(conn)
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
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

def get_target_verifikasi(kategori="A", pengisi="Farid Akbar Arifandi", hanya_belum_verif=True, limit=50):
    """
    Mengambil daftar baris yang dikerjakan oleh pengisi tertentu (Farid Akbar Arifandi)
    untuk keperluan verifikasi ulang catatan/remark dan kesesuaian nilai di FASIH.
    """
    conn = get_connection()
    query = "SELECT * FROM kasus_nerwana WHERE tindak_lanjut_oleh LIKE ?"
    params = [f"%{pengisi}%"]
    
    if kategori and kategori.upper() != "SEMUA":
        query += " AND UPPER(kategori) = ?"
        params.append(kategori.upper().strip())
        
    if hanya_belum_verif:
        query += " AND (remark_terverifikasi = 0 OR remark_terverifikasi IS NULL)"
        
    query += " ORDER BY assignment_id ASC LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

if __name__ == "__main__":
    init_db()

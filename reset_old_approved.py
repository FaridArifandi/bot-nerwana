"""
reset_old_approved.py
Mereset 352 baris berstatus APPROVED dari heuristik lama kembali ke PENDING.
Sesuai PRD Refactor Bot Nerwana (Tugas 6).
Nilai-nilai usulan lama dibersihkan agar tidak ada eksekusi berbasis angka heuristik lama.
"""

from database import get_connection, log_audit

def reset_approved_rows():
    conn = get_connection()
    cursor = conn.cursor()
    
    rows = cursor.execute("SELECT assignment_id, nama_usaha FROM kasus_nerwana WHERE status = 'APPROVED'").fetchall()
    total = len(rows)
    print(f"[RESET] Ditemukan {total} baris berstatus 'APPROVED' lama.")
    
    if total == 0:
        print("[RESET] Tidak ada baris APPROVED yang perlu direset.")
        conn.close()
        return 0
        
    cursor.execute("""
    UPDATE kasus_nerwana SET
        status = 'PENDING',
        alasan_review = 'Reset dari APPROVED heuristik lama ke PENDING untuk evaluasi ulang dari FASIH',
        updated_at = CURRENT_TIMESTAMP
    WHERE status = 'APPROVED'
    """)
    conn.commit()
    print(f"[RESET] Berhasil mereset {total} baris menjadi 'PENDING'.")
    
    # Audit log ringkasan
    log_audit("BATCH_RESET", "ALL_APPROVED", "RESET_HEURISTIK_LAMA",
              status_sebelumnya="APPROVED", status_baru="PENDING",
              pesan=f"Reset {total} baris APPROVED ke PENDING sesuai PRD Tugas 6")
              
    conn.close()
    return total

if __name__ == '__main__':
    reset_approved_rows()

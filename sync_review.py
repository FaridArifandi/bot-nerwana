import os
import sqlite3
import openpyxl

from database import get_connection, log_audit

EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_usulan.xlsx")

def sync_excel_to_db():
    if not os.path.exists(EXCEL_PATH):
        print(f"[ERROR] File {EXCEL_PATH} tidak ditemukan.")
        return 0

    print(f"Membaca file {EXCEL_PATH}...")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb["Review Usulan Flag 3"]

    conn = get_connection()
    cursor = conn.cursor()

    approved_count = 0
    updated_count = 0

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        aid = str(row[1] or '').strip()
        nama = str(row[2] or '').strip()
        if not aid or not nama:
            continue

        # Data usulan dari Excel (jika user ada mengedit di Excel)
        pbj_usulan = float(row[10] or 0)
        prod_usulan = float(row[11] or 0)
        ops_usulan = float(row[12] or 0)
        rasio_baru = float(row[14] or 0)
        kode_catatan = str(row[16] or '').strip()
        alasan = str(row[17] or '').strip()
        approved_val = str(row[19] or '').strip().upper()
        catatan_reviewer = str(row[20] or '').strip()

        # Tentukan status baru
        if approved_val == 'Y':
            new_status = 'APPROVED'
            approved_count += 1
        else:
            new_status = 'PENDING'

        # Cek apakah status di DB sudah APPLIED / SUBMITTED / COMPLETED / MARKED (jangan ditimpa ke APPROVED jika sudah selesai)
        cur = cursor.execute("SELECT status, tindak_lanjut FROM kasus_nerwana WHERE assignment_id = ? AND nama_usaha = ?", (aid, nama)).fetchone()
        if cur and (cur['status'] in ['APPLIED', 'SUBMITTED', 'MARKED', 'COMPLETED'] or cur['tindak_lanjut'] == 'sudah_direvisi'):
            continue

        cursor.execute("""
        UPDATE kasus_nerwana SET
            nilai_baru_pbj = ?,
            nilai_baru_prod = ?,
            nilai_baru_ops = ?,
            rasio_baru = ?,
            kode_catatan = ?,
            alasan_usulan = ?,
            status = ?,
            alasan_review = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE assignment_id = ? AND nama_usaha = ?
        """, (
            pbj_usulan, prod_usulan, ops_usulan, rasio_baru, kode_catatan, alasan,
            new_status, catatan_reviewer, aid, nama
        ))
        updated_count += 1

    conn.commit()
    conn.close()
    wb.close()

    print(f"[SYNC] Selesai menyinkronkan {updated_count} baris dari Excel.")
    print(f"[SYNC] Total kasus siap dieksekusi (status APPROVED): {approved_count} baris.")
    return approved_count

if __name__ == "__main__":
    sync_excel_to_db()

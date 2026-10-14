import os
import sqlite3
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import DB_PATH, get_connection
from threshold_manager import get_threshold

EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_usulan.xlsx")

def calculate_usulan(row, kategori=None):
    pbj = float(row['pbj'] or 0)
    prod = float(row['prod'] or 0)
    ops = float(row['ops'] or 0)
    beli = float(row['beli'] or 0)
    rasio = float(row['rasio'] or 0)
    ntb = float(row['ntb'] or 0)
    output = float(row['output'] or 0)
    
    kat = str(row.get('kategori') if isinstance(row, dict) and row.get('kategori') else (kategori or "G")).upper().strip()
    kbli = str(row.get('kbli') if isinstance(row, dict) and row.get('kbli') else "").strip()
    
    # Resolusi Threshold Hierarkis Dinamis (KBLI 5 -> 3 -> 2 -> Kategori -> Generic)
    thresh = get_threshold(kat, kbli, skala="mikro_kecil")
    MIN_RATIO = thresh['min']
    MAX_RATIO = thresh['max']
    TARGET_RATIO = thresh['target']
    THRESH_LEVEL = thresh['level']
    THRESH_LABEL = f"{THRESH_LEVEL} [{MIN_RATIO:.2f} - {MAX_RATIO:.2f}]"
    
    # 1. PENGECUALIAN KHUSUS (NEED_REVIEW)
    if pbj == 0 and (prod > 0 or ops > 0 or beli > 0):
        alasan = f"PBJ = 0 (pengeluaran ada). Indikasi belum ada omzet / baru beroperasi / gagal panen ({THRESH_LABEL})."
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': rasio,
            'skor': 50,
            'alasan': alasan,
            'kode_catatan': "",
            'status': "NEED_REVIEW",
            'acuan_threshold': THRESH_LABEL
        }
        
    if pbj == 0 and prod == 0 and ops == 0 and beli == 0:
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': 0,
            'skor': 30,
            'alasan': f"Semua nilai biaya & pendapatan 0 ({THRESH_LABEL}). Butuh konfirmasi lapangan.",
            'kode_catatan': "",
            'status': "NEED_REVIEW",
            'acuan_threshold': THRESH_LABEL
        }

    # 2. SUDAH DI DALAM RENTANG THRESHOLD
    if MIN_RATIO <= rasio <= MAX_RATIO:
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': rasio,
            'skor': 100,
            'alasan': f"Sudah dalam rentang threshold {THRESH_LABEL}. Tidak perlu perbaikan.",
            'kode_catatan': "",
            'status': "SKIP",
            'acuan_threshold': THRESH_LABEL
        }

    # ----------------------------------------------------
    # CABANG 1: LOGIKA KHUSUS KATEGORI G (PERDAGANGAN)
    # Sensenya: Menaikkan pendapatan / nilai produksi kuesioner 27.a (PBJ)
    # dan menyematkan remark catatan #DC_01
    # ----------------------------------------------------
    if kat == "G":
        # 1a. Cek kemungkinan kekurangan nol pada PBJ (pbj * 10)
        if pbj > 0:
            cand_pbj = pbj * 10
            cand_ntb = cand_pbj - prod - ops - beli
            cand_out = cand_pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    return {
                        'pbj_baru': cand_pbj,
                        'prod_baru': prod,
                        'ops_baru': ops,
                        'rasio_baru': cand_r,
                        'skor': 98,
                        'alasan': f"Dugaan kekurangan nol pada PBJ ({int(pbj):,} -> {int(cand_pbj):,}) | {THRESH_LABEL}",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING",
                        'acuan_threshold': THRESH_LABEL
                    }

        # 1b. Kasus rasio < MIN_RATIO: Menaikkan Pendapatan (Kuesioner 27.a / PBJ) ke target rasio
        if rasio < MIN_RATIO:
            p_ops = prod + ops
            if p_ops > 0 or beli > 0:
                ideal_pbj = (p_ops / (1.0 - TARGET_RATIO)) + beli
                cand_pbj = round(ideal_pbj / 1000) * 1000
                cand_ntb = cand_pbj - prod - ops - beli
                cand_out = cand_pbj - beli
                if cand_out > 0:
                    cand_r = cand_ntb / cand_out
                    if MIN_RATIO <= cand_r <= MAX_RATIO:
                        ratio_kenaikan = cand_pbj / pbj if pbj > 0 else 999
                        skor = 90 if ratio_kenaikan <= 5 else 80
                        return {
                            'pbj_baru': cand_pbj,
                            'prod_baru': prod,
                            'ops_baru': ops,
                            'rasio_baru': cand_r,
                            'skor': skor,
                            'alasan': f"Naikkan Pendapatan (Kues 27.a / PBJ) ke target rasio {cand_r:.2f} ({THRESH_LABEL})",
                            'kode_catatan': "#DC_01",
                            'status': "PENDING",
                            'acuan_threshold': THRESH_LABEL
                        }

        # 1c. Kasus rasio > MAX_RATIO (pengeluaran terlalu kecil)
        if rasio > MAX_RATIO and pbj > 0:
            if ops > 0:
                cand_ops = ops * 10
                cand_ntb = pbj - prod - cand_ops - beli
                cand_out = pbj - beli
                if cand_out > 0:
                    cand_r = cand_ntb / cand_out
                    if MIN_RATIO <= cand_r <= MAX_RATIO:
                        return {
                            'pbj_baru': pbj,
                            'prod_baru': prod,
                            'ops_baru': cand_ops,
                            'rasio_baru': cand_r,
                            'skor': 90,
                            'alasan': f"Dugaan kekurangan nol pada Biaya Operasional ({int(ops):,} -> {int(cand_ops):,}) | {THRESH_LABEL}",
                            'kode_catatan': "#DC_01",
                            'status': "PENDING",
                            'acuan_threshold': THRESH_LABEL
                        }
            return {
                'pbj_baru': pbj,
                'prod_baru': prod,
                'ops_baru': ops,
                'rasio_baru': rasio,
                'skor': 45,
                'alasan': f"Rasio di atas threshold ({rasio:.2f} > {MAX_RATIO:.2f} | {THRESH_LABEL}). Perlu tinjauan manual.",
                'kode_catatan': "",
                'status': "NEED_REVIEW",
                'acuan_threshold': THRESH_LABEL
            }

        # Fallback G
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': rasio,
            'skor': 40,
            'alasan': f"Pola ekstrem/anomali Kategori G ({THRESH_LABEL}). Memerlukan tinjauan manual.",
            'kode_catatan': "",
            'status': "NEED_REVIEW",
            'acuan_threshold': THRESH_LABEL
        }

    # ----------------------------------------------------
    # CABANG 2: LOGIKA KATEGORI C (INDUSTRI PENGOLAHAN)
    # Sensenya: Biaya bahan baku/produksi (prod) tinggi
    # ----------------------------------------------------
    if kat == "C":
        # 2a. Biaya Produksi kelebihan nol (prod / 10)
        if prod >= 10000:
            cand_prod = round(prod / 10 / 1000) * 1000
            cand_ntb = pbj - cand_prod - ops - beli
            cand_out = pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    return {
                        'pbj_baru': pbj,
                        'prod_baru': cand_prod,
                        'ops_baru': ops,
                        'rasio_baru': cand_r,
                        'skor': 98,
                        'alasan': f"Dugaan kelebihan nol pada Biaya Produksi ({int(prod):,} -> {int(cand_prod):,}) | {THRESH_LABEL}",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING",
                        'acuan_threshold': THRESH_LABEL
                    }

        # 2b. Biaya Operasional kelebihan nol (ops / 10)
        if ops >= 10000:
            cand_ops = round(ops / 10 / 1000) * 1000
            cand_ntb = pbj - prod - cand_ops - beli
            cand_out = pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    return {
                        'pbj_baru': pbj,
                        'prod_baru': prod,
                        'ops_baru': cand_ops,
                        'rasio_baru': cand_r,
                        'skor': 95,
                        'alasan': f"Dugaan kelebihan nol pada Biaya Operasional ({int(ops):,} -> {int(cand_ops):,}) | {THRESH_LABEL}",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING",
                        'acuan_threshold': THRESH_LABEL
                    }

        # 2c. PBJ kekurangan nol (pbj * 10)
        if pbj > 0:
            cand_pbj = pbj * 10
            cand_ntb = cand_pbj - prod - ops - beli
            cand_out = cand_pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    return {
                        'pbj_baru': cand_pbj,
                        'prod_baru': prod,
                        'ops_baru': ops,
                        'rasio_baru': cand_r,
                        'skor': 96,
                        'alasan': f"Dugaan kekurangan nol pada PBJ ({int(pbj):,} -> {int(cand_pbj):,}) | {THRESH_LABEL}",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING",
                        'acuan_threshold': THRESH_LABEL
                    }

        # 2d. Jika rasio < MIN_RATIO: Naikkan PBJ ke target rasio
        if rasio < MIN_RATIO:
            total_exp = prod + ops + beli
            if total_exp > 0:
                ideal_pbj = total_exp / (1.0 - TARGET_RATIO)
                cand_pbj = round(ideal_pbj / 1000) * 1000
                cand_ntb = cand_pbj - prod - ops - beli
                cand_out = cand_pbj - beli
                if cand_out > 0:
                    cand_r = cand_ntb / cand_out
                    if MIN_RATIO <= cand_r <= MAX_RATIO:
                        return {
                            'pbj_baru': cand_pbj,
                            'prod_baru': prod,
                            'ops_baru': ops,
                            'rasio_baru': cand_r,
                            'skor': 85,
                            'alasan': f"Naikkan PBJ ke target rasio {cand_r:.2f} ({THRESH_LABEL})",
                            'kode_catatan': "#DC_01",
                            'status': "PENDING",
                            'acuan_threshold': THRESH_LABEL
                        }

        # 2e. Jika rasio > MAX_RATIO: Pengeluaran terlalu kecil, sesuaikan biaya produksi
        if rasio > MAX_RATIO and pbj > 0:
            target_exp = pbj * (1.0 - TARGET_RATIO)
            cand_prod = round(target_exp / 1000) * 1000
            cand_ntb = pbj - cand_prod - ops - beli
            cand_out = pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    return {
                        'pbj_baru': pbj,
                        'prod_baru': cand_prod,
                        'ops_baru': ops,
                        'rasio_baru': cand_r,
                        'skor': 80,
                        'alasan': f"Sesuaikan biaya produksi ke target rasio {cand_r:.2f} ({THRESH_LABEL})",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING",
                        'acuan_threshold': THRESH_LABEL
                    }

        # Fallback C
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': rasio,
            'skor': 40,
            'alasan': f"Pola ekstrem/anomali Kategori C ({THRESH_LABEL}). Memerlukan tinjauan manual.",
            'kode_catatan': "",
            'status': "NEED_REVIEW",
            'acuan_threshold': THRESH_LABEL
        }

    # ----------------------------------------------------
    # CABANG 3: LOGIKA KATEGORI A (PERTANIAN) & KATEGORI LAINNYA
    # ----------------------------------------------------
    # 3a. Biaya Produksi kelebihan nol (prod / 10)
    if prod >= 10000:
        cand_prod = round(prod / 10 / 1000) * 1000
        cand_ntb = pbj - cand_prod - ops - beli
        cand_out = pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if MIN_RATIO <= cand_r <= MAX_RATIO:
                return {
                    'pbj_baru': pbj,
                    'prod_baru': cand_prod,
                    'ops_baru': ops,
                    'rasio_baru': cand_r,
                    'skor': 98,
                    'alasan': f"Dugaan kelebihan nol pada Biaya Produksi ({int(prod):,} -> {int(cand_prod):,}) | {THRESH_LABEL}",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING",
                    'acuan_threshold': THRESH_LABEL
                }

    # 3b. Biaya Operasional kelebihan nol (ops / 10)
    if ops >= 10000:
        cand_ops = round(ops / 10 / 1000) * 1000
        cand_ntb = pbj - prod - cand_ops - beli
        cand_out = pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if MIN_RATIO <= cand_r <= MAX_RATIO:
                return {
                    'pbj_baru': pbj,
                    'prod_baru': prod,
                    'ops_baru': cand_ops,
                    'rasio_baru': cand_r,
                    'skor': 95,
                    'alasan': f"Dugaan kelebihan nol pada Biaya Operasional ({int(ops):,} -> {int(cand_ops):,}) | {THRESH_LABEL}",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING",
                    'acuan_threshold': THRESH_LABEL
                }

    # 3c. PBJ kekurangan nol (pbj * 10)
    if pbj > 0:
        cand_pbj = pbj * 10
        cand_ntb = cand_pbj - prod - ops - beli
        cand_out = cand_pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if MIN_RATIO <= cand_r <= MAX_RATIO:
                return {
                    'pbj_baru': cand_pbj,
                    'prod_baru': prod,
                    'ops_baru': ops,
                    'rasio_baru': cand_r,
                    'skor': 96,
                    'alasan': f"Dugaan kekurangan nol pada PBJ ({int(pbj):,} -> {int(cand_pbj):,}) | {THRESH_LABEL}",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING",
                    'acuan_threshold': THRESH_LABEL
                }

    # 3d. Jika rasio > MAX_RATIO (pengeluaran terlalu kecil) -> cek apakah prod * 10
    if rasio > MAX_RATIO and prod > 0:
        cand_prod = prod * 10
        cand_ntb = pbj - cand_prod - ops - beli
        cand_out = pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if MIN_RATIO <= cand_r <= MAX_RATIO:
                return {
                    'pbj_baru': pbj,
                    'prod_baru': cand_prod,
                    'ops_baru': ops,
                    'rasio_baru': cand_r,
                    'skor': 92,
                    'alasan': f"Dugaan kekurangan nol pada Biaya Produksi ({int(prod):,} -> {int(cand_prod):,}) | {THRESH_LABEL}",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING",
                    'acuan_threshold': THRESH_LABEL
                }

    # 3e. Menaikkan pendapatan (PBJ) ke TARGET_RATIO
    total_exp = prod + ops + beli
    if rasio < MIN_RATIO:
        if total_exp > 0:
            ideal_pbj = total_exp / (1.0 - TARGET_RATIO)
            cand_pbj = round(ideal_pbj / 1000) * 1000
            cand_ntb = cand_pbj - prod - ops - beli
            cand_out = cand_pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    ratio_kenaikan = cand_pbj / pbj if pbj > 0 else 999
                    skor = 85 if ratio_kenaikan <= 5 else 78
                    return {
                        'pbj_baru': cand_pbj,
                        'prod_baru': prod,
                        'ops_baru': ops,
                        'rasio_baru': cand_r,
                        'skor': skor,
                        'alasan': f"Naikkan PBJ ke target rasio {cand_r:.2f} ({THRESH_LABEL})",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING",
                        'acuan_threshold': THRESH_LABEL
                    }

    # 3f. Penyesuaian Pengeluaran Turun proporsional
    if rasio < MIN_RATIO and pbj > 0:
        target_exp = pbj * (1.0 - TARGET_RATIO)
        cur_exp = prod + ops
        if cur_exp > 0:
            scale = target_exp / cur_exp
            cand_prod = round((prod * scale) / 1000) * 1000
            cand_ops = round((ops * scale) / 1000) * 1000
            cand_ntb = pbj - cand_prod - cand_ops - beli
            cand_out = pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    return {
                        'pbj_baru': pbj,
                        'prod_baru': cand_prod,
                        'ops_baru': cand_ops,
                        'rasio_baru': cand_r,
                        'skor': 80,
                        'alasan': f"Turunkan pengeluaran proporsional ke target rasio {cand_r:.2f} ({THRESH_LABEL})",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING",
                        'acuan_threshold': THRESH_LABEL
                    }

    # 3g. Rasio Terlalu Tinggi (> MAX_RATIO)
    if rasio > MAX_RATIO and pbj > 0:
        target_exp = pbj * (1.0 - TARGET_RATIO)
        cand_prod = round(target_exp / 1000) * 1000
        cand_ntb = pbj - cand_prod - ops - beli
        cand_out = pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if MIN_RATIO <= cand_r <= MAX_RATIO:
                return {
                    'pbj_baru': pbj,
                    'prod_baru': cand_prod,
                    'ops_baru': ops,
                    'rasio_baru': cand_r,
                    'skor': 75,
                    'alasan': f"Naikkan biaya produksi ke target rasio {cand_r:.2f} ({THRESH_LABEL})",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING",
                    'acuan_threshold': THRESH_LABEL
                }

    # Fallback Umum
    return {
        'pbj_baru': pbj,
        'prod_baru': prod,
        'ops_baru': ops,
        'rasio_baru': rasio,
        'skor': 40,
        'alasan': f"Pola ekstrem/anomali ({THRESH_LABEL}). Memerlukan tinjauan manual.",
        'kode_catatan': "",
        'status': "NEED_REVIEW",
        'acuan_threshold': THRESH_LABEL
    }

def process_and_export():
    print("=" * 65)
    print("           FASE 2: KALKULATOR USULAN & EKSPOR EXCEL")
    print("=" * 65)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    rows = cursor.execute("SELECT * FROM kasus_nerwana ORDER BY rasio ASC").fetchall()
    total = len(rows)
    print(f"Total kasus yang diproses: {total} baris...")
    
    # Update SQLite
    update_data = []
    export_rows = []
    
    for r in rows:
        res = calculate_usulan(r)
        
        # Simpan usulan ke database (hanya jika belum APPLIED / SUBMITTED)
        current_status = r['status']
        new_status = res['status']
        if current_status in ['APPROVED', 'APPLIED', 'SUBMITTED', 'MARKED']:
            new_status = current_status
            
        update_data.append((
            res['pbj_baru'],
            res['prod_baru'],
            res['ops_baru'],
            res['rasio_baru'],
            res['skor'],
            res['alasan'],
            res['kode_catatan'],
            new_status,
            r['assignment_id'],
            r['nama_usaha']
        ))
        
        export_rows.append({
            'row': r,
            'usulan': res,
            'final_status': new_status
        })

    cursor.executemany("""
    UPDATE kasus_nerwana SET
        nilai_baru_pbj = ?,
        nilai_baru_prod = ?,
        nilai_baru_ops = ?,
        rasio_baru = ?,
        skor_usulan = ?,
        alasan_usulan = ?,
        kode_catatan = ?,
        status = ?,
        updated_at = CURRENT_TIMESTAMP
    WHERE assignment_id = ? AND nama_usaha = ?
    """, update_data)
    
    conn.commit()
    print(f"[SQLITE] Berhasil memperbarui {len(update_data)} baris usulan di database.")

    # Generate Excel via openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Review Usulan Flag 3"
    ws.views.sheetView[0].showGridLines = True

    headers = [
        "NO", "ASSIGNMENT_ID", "NAMA_USAHA", "KBLI", "DESKRIPSI_KBLI",
        "PBJ_LAMA", "PROD_LAMA", "OPS_LAMA", "NTB_LAMA", "RASIO_LAMA",
        "PBJ_USULAN", "PROD_USULAN", "OPS_USULAN", "NTB_USULAN", "RASIO_BARU",
        "SKOR", "KODE_CATATAN", "ALASAN_USULAN", "STATUS",
        "APPROVED", "CATATAN_REVIEWER", "TINDAK_LANJUT_NERWANA", "LINK_FASIH",
        "ACUAN_THRESHOLD"
    ]
    
    ws.append(headers)

    # Styles
    font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    font_approved_hdr = Font(name="Calibri", size=11, bold=True, color="000000")
    fill_header = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    fill_approved = PatternFill(start_color="FFD966", end_color="FFD966", fill_type="solid") # Gold/Yellow
    
    fill_green_safe = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    fill_yellow_review = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    fill_gray_skip = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    font_red = Font(name="Calibri", size=10, color="9C0006", bold=True)
    font_bold = Font(name="Calibri", size=10, bold=True)
    font_normal = Font(name="Calibri", size=10)

    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )

    # Format Header Row
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
        if headers[col_idx - 1] == "APPROVED":
            cell.font = font_approved_hdr
            cell.fill = fill_approved
        else:
            cell.font = font_header
            cell.fill = fill_header

    ws.row_dimensions[1].height = 28

    # Populate Data
    row_num = 2
    for idx, item in enumerate(export_rows, start=1):
        r = item['row']
        u = item['usulan']
        final_status = item['final_status']
        
        ntb_usulan = u['pbj_baru'] - u['prod_baru'] - u['ops_baru'] - (r['beli'] or 0)
        
        # Nilai approved awal: 'Y' untuk PENDING berkategori skor tinggi, atau kosong
        approved_val = ""
        if final_status == "PENDING" and u['skor'] >= 90:
            approved_val = "Y" # Rekomendasi awal, reviewer tetap bisa uncheck

        data_row = [
            idx,
            r['assignment_id'],
            r['nama_usaha'],
            r['kbli'],
            r['deskripsi_kbli'],
            r['pbj'],
            r['prod'],
            r['ops'],
            r['ntb'],
            r['rasio'],
            u['pbj_baru'],
            u['prod_baru'],
            u['ops_baru'],
            ntb_usulan,
            u['rasio_baru'],
            u['skor'],
            u['kode_catatan'],
            u['alasan'],
            final_status,
            approved_val,
            "", # CATATAN_REVIEWER
            r['tindak_lanjut'] or "belum",
            r['link_fasih'],
            u.get('acuan_threshold', '')
        ]
        
        ws.append(data_row)
        curr_row = ws[row_num]
        
        # Apply formatting per cell
        for col_idx in range(1, len(headers) + 1):
            c = curr_row[col_idx - 1]
            c.border = thin_border
            c.font = font_normal
            
            # Formats
            # Numbers / Currency
            if col_idx in [6, 7, 8, 9, 11, 12, 13, 14]:
                c.number_format = '#,##0'
                c.alignment = Alignment(horizontal="right", vertical="center")
            # Rasio
            elif col_idx in [10, 15]:
                c.number_format = '0.0000'
                c.alignment = Alignment(horizontal="right", vertical="center")
            # Alignment center
            elif col_idx in [1, 2, 4, 16, 17, 19, 20]:
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(horizontal="left", vertical="center")

            # Conditional Colors
            if col_idx == 10: # RASIO LAMA
                if r['rasio'] < 0.50 or r['rasio'] > 0.90:
                    c.font = font_red
            elif col_idx == 15: # RASIO BARU
                if 0.50 <= u['rasio_baru'] <= 0.90:
                    c.fill = fill_green_safe
                    c.font = font_bold
            elif col_idx == 19: # STATUS
                if final_status == "NEED_REVIEW":
                    c.fill = fill_yellow_review
                    c.font = font_bold
                elif final_status == "SKIP":
                    c.fill = fill_gray_skip
            elif col_idx == 20: # APPROVED
                if c.value == "Y":
                    c.font = font_bold
                    c.fill = fill_approved

        ws.row_dimensions[row_num].height = 20
        row_num += 1

    # Freeze panes at D2 (baris 1 dan kolom A-C tetap terlihat)
    ws.freeze_panes = 'D2'
    
    # Auto-fit column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col[:100]: # Sample 100 baris untuk hitung lebar
            val_str = str(cell.value or '')
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 10), 45)

    ws.column_dimensions['A'].width = 6   # NO
    ws.column_dimensions['B'].width = 38  # ASSIGNMENT_ID
    ws.column_dimensions['C'].width = 30  # NAMA_USAHA
    ws.column_dimensions['Q'].width = 16  # KODE_CATATAN
    ws.column_dimensions['R'].width = 45  # ALASAN_USULAN
    ws.column_dimensions['T'].width = 12  # APPROVED
    ws.column_dimensions['W'].width = 30  # LINK_FASIH
    ws.column_dimensions['X'].width = 28  # ACUAN_THRESHOLD

    wb.save(EXCEL_PATH)
    conn.close()
    
    print("\n" + "=" * 65)
    print(f"FASE 2 SELESAI!")
    print(f"File Excel Review Berhasil Dibuat: {EXCEL_PATH}")
    print("=" * 65)

if __name__ == "__main__":
    process_and_export()

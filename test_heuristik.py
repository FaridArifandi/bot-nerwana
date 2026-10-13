import sqlite3
import math

def calculate_usulan(row):
    pbj = float(row['pbj'] or 0)
    prod = float(row['prod'] or 0)
    ops = float(row['ops'] or 0)
    beli = float(row['beli'] or 0)
    rasio = float(row['rasio'] or 0)
    ntb = float(row['ntb'] or 0)
    output = float(row['output'] or 0)
    nama = row['nama_usaha'].upper()
    
    # Target tengah rentang (0.60 - 0.85) -> default 0.70
    TARGET_RATIO = 0.70
    
    # 1. PENGECUALIAN KHUSUS (NEED_REVIEW)
    # Jika PBJ = 0 tapi ada pengeluaran (indikasi belum panen atau gagal panen)
    if pbj == 0 and (prod > 0 or ops > 0):
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': rasio,
            'skor': 50,
            'alasan': "PBJ = 0 (pengeluaran ada). Kemungkinan belum panen / gagal panen / banjir.",
            'kode_catatan': "",
            'status': "NEED_REVIEW"
        }
        
    # Jika PBJ = 0 dan pengeluaran = 0
    if pbj == 0 and prod == 0 and ops == 0:
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': 0,
            'skor': 30,
            'alasan': "Semua nilai 0. Butuh konfirmasi lapangan.",
            'kode_catatan': "",
            'status': "NEED_REVIEW"
        }

    # Jika sudah di dalam rentang 0.51 - 0.94
    if 0.51 <= rasio <= 0.94:
        return {
            'pbj_baru': pbj,
            'prod_baru': prod,
            'ops_baru': ops,
            'rasio_baru': rasio,
            'skor': 100,
            'alasan': "Sudah dalam rentang threshold (0.51 - 0.94). Tidak perlu perbaikan.",
            'kode_catatan': "",
            'status': "SKIP"
        }

    # 2. HEURISTIK 1: DUGAAN SALAH KETIK NOL (x10 atau /10)
    # 2a. Biaya Produksi kelebihan nol (prod / 10)
    if prod >= 10000:
        cand_prod = round(prod / 10 / 1000) * 1000
        cand_ntb = pbj - cand_prod - ops - beli
        cand_out = pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if 0.55 <= cand_r <= 0.90:
                return {
                    'pbj_baru': pbj,
                    'prod_baru': cand_prod,
                    'ops_baru': ops,
                    'rasio_baru': cand_r,
                    'skor': 98,
                    'alasan': f"Dugaan kelebihan nol pada Biaya Produksi ({int(prod):,} -> {int(cand_prod):,})",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING"
                }

    # 2b. Biaya Operasional kelebihan nol (ops / 10)
    if ops >= 10000:
        cand_ops = round(ops / 10 / 1000) * 1000
        cand_ntb = pbj - prod - cand_ops - beli
        cand_out = pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if 0.55 <= cand_r <= 0.90:
                return {
                    'pbj_baru': pbj,
                    'prod_baru': prod,
                    'ops_baru': cand_ops,
                    'rasio_baru': cand_r,
                    'skor': 95,
                    'alasan': f"Dugaan kelebihan nol pada Biaya Operasional ({int(ops):,} -> {int(cand_ops):,})",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING"
                }

    # 2c. PBJ kekurangan nol (pbj * 10)
    if pbj > 0:
        cand_pbj = pbj * 10
        cand_ntb = cand_pbj - prod - ops - beli
        cand_out = cand_pbj - beli
        if cand_out > 0:
            cand_r = cand_ntb / cand_out
            if 0.55 <= cand_r <= 0.90:
                return {
                    'pbj_baru': cand_pbj,
                    'prod_baru': prod,
                    'ops_baru': ops,
                    'rasio_baru': cand_r,
                    'skor': 96,
                    'alasan': f"Dugaan kekurangan nol pada PBJ ({int(pbj):,} -> {int(cand_pbj):,})",
                    'kode_catatan': "#DC_01",
                    'status': "PENDING"
                }

    # 2d. Jika rasio > 0.94 (pengeluaran terlalu kecil) -> cek apakah prod * 10 atau ops * 10
    if rasio > 0.94:
        if prod > 0:
            cand_prod = prod * 10
            cand_ntb = pbj - cand_prod - ops - beli
            cand_out = pbj - beli
            if cand_out > 0:
                cand_r = cand_ntb / cand_out
                if 0.55 <= cand_r <= 0.90:
                    return {
                        'pbj_baru': pbj,
                        'prod_baru': cand_prod,
                        'ops_baru': ops,
                        'rasio_baru': cand_r,
                        'skor': 92,
                        'alasan': f"Dugaan kekurangan nol pada Biaya Produksi ({int(prod):,} -> {int(cand_prod):,})",
                        'kode_catatan': "#DC_01",
                        'status': "PENDING"
                    }

    # 3. HEURISTIK 2: NAIKKAN PENDAPATAN (PBJ)
    # Asumsi: responden jujur pengeluaran, omzet under-reported
    # Target rasio: 0.70
    # Formula: PBJ_target = (prod + ops) / (1 - 0.70) = (prod + ops) / 0.30
    total_exp = prod + ops + beli
    if rasio < 0.51:
        if total_exp > 0:
            ideal_pbj = total_exp / (1.0 - TARGET_RATIO)
            # Bulatkan ke ribuan
            cand_pbj = round(ideal_pbj / 1000) * 1000
            
            # Recalculate rasio dengan angka yang sudah dibulatkan
            cand_ntb = cand_pbj - prod - ops - beli
            cand_out = cand_pbj - beli
            cand_r = cand_ntb / cand_out
            
            # Pastikan masuk rentang aman 0.55 - 0.85
            if 0.55 <= cand_r <= 0.85:
                # Cek rasio kenaikan
                ratio_kenaikan = cand_pbj / pbj if pbj > 0 else 999
                skor = 85 if ratio_kenaikan <= 5 else 78
                return {
                    'pbj_baru': cand_pbj,
                    'prod_baru': prod,
                    'ops_baru': ops,
                    'rasio_baru': cand_r,
                    'skor': skor,
                    'alasan': f"Naikkan PBJ ke target rasio {cand_r:.2f} (asumsi pengeluaran riil, omzet under-reported)",
                    'kode_catatan': "",
                    'status': "PENDING"
                }

    # 4. HEURISTIK 3: PENYESUAIAN PENGELUARAN TURUN (Jika PBJ sudah sangat besar)
    # Jika rasio < 0.51 tapi kenaikan PBJ tidak memungkinkan atau alternatif
    if rasio < 0.51 and pbj > 0:
        # Target total pengeluaran = pbj * (1 - TARGET_RATIO) = pbj * 0.30
        target_exp = pbj * (1.0 - TARGET_RATIO)
        # Kurangi secara proporsional dari prod & ops
        cur_exp = prod + ops
        if cur_exp > 0:
            scale = target_exp / cur_exp
            cand_prod = round((prod * scale) / 1000) * 1000
            cand_ops = round((ops * scale) / 1000) * 1000
            cand_ntb = pbj - cand_prod - cand_ops - beli
            cand_out = pbj - beli
            cand_r = cand_ntb / cand_out
            if 0.55 <= cand_r <= 0.85:
                return {
                    'pbj_baru': pbj,
                    'prod_baru': cand_prod,
                    'ops_baru': cand_ops,
                    'rasio_baru': cand_r,
                    'skor': 80,
                    'alasan': f"Turunkan pengeluaran proporsional ke target rasio {cand_r:.2f}",
                    'kode_catatan': "",
                    'status': "PENDING"
                }

    # 5. HEURISTIK 4: RASIO TERLALU TINGGI (> 0.94)
    # Artinya pengeluaran dilaporkan terlalu minim
    if rasio > 0.94 and pbj > 0:
        # Target pengeluaran = pbj * (1 - 0.70) = pbj * 0.30
        target_exp = pbj * (1.0 - TARGET_RATIO)
        cand_prod = round(target_exp / 1000) * 1000
        cand_ntb = pbj - cand_prod - ops - beli
        cand_out = pbj - beli
        cand_r = cand_ntb / cand_out
        if 0.55 <= cand_r <= 0.85:
            return {
                'pbj_baru': pbj,
                'prod_baru': cand_prod,
                'ops_baru': ops,
                'rasio_baru': cand_r,
                'skor': 75,
                'alasan': f"Naikkan biaya produksi (pengeluaran awal terlalu mendekati nol, target rasio {cand_r:.2f})",
                'kode_catatan': "",
                'status': "PENDING"
            }

    # Fallback
    return {
        'pbj_baru': pbj,
        'prod_baru': prod,
        'ops_baru': ops,
        'rasio_baru': rasio,
        'skor': 40,
        'alasan': "Pola ekstrem/anomali. Memerlukan tinjauan manual.",
        'kode_catatan': "",
        'status': "NEED_REVIEW"
    }

if __name__ == "__main__":
    conn = sqlite3.connect('data_cleaning.db')
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM kasus_nerwana LIMIT 10").fetchall()
    for r in rows:
        res = calculate_usulan(r)
        print(f"[{r['nama_usaha'][:25]}] Rasio Lama: {r['rasio']:.4f} -> Baru: {res['rasio_baru']:.4f} | Skor: {res['skor']} | Status: {res['status']}")
        print(f"  Alasan: {res['alasan']}")
    conn.close()

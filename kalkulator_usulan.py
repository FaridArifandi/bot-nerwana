import os
import sqlite3
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import DB_PATH, get_connection
from threshold_manager import get_threshold
from config import TOL_RASIO_SELANCAR, FAKTOR_KALI, FAKTOR_BAGI, CAP_NILAI_BARU

EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_usulan.xlsx")


class HasilEvaluasi(dict):
    """
    Subclass dict yang kompatibel dua arah:
    - Dict key: res['status'], res['field'], res['nilai_baru'], dll.
    - Dot attribute: res.status, res.aksi, res.field, res.nilai_baru, res.faktor, res.operasi, dll.
    """
    def __getattr__(self, name):
        if name == 'aksi':
            return self.get('status')
        if name == 'faktor':
            op = self.get('operasi')
            if op == 'x10':
                return 10
            elif op == ':10':
                return 0.1
            nl = self.get('nilai_lama')
            nb = self.get('nilai_baru')
            if nl and nb and nl > 0:
                return round(nb / nl, 4)
            return None
        if name in self:
            return self[name]
        return None


def evaluasi(nilai: dict, kategori: str, kbli: str, blok: str = "biasa", rasio_selancar: float = None) -> HasilEvaluasi:
    """
    Evaluasi nilai FASIH untuk usulan koreksi sesuai Guardrail G1-G8 (PRD §6).
    Fungsi murni tanpa I/O.
    
    Parameters:
        nilai: dict berisi {'pbj': int/float, 'prod': int/float, 'ops': int/float, 'beli': int/float}
        kategori: kode kategori KBLI (mis. 'A', 'C', 'G')
        kbli: 5 digit KBLI (mis. '47111', '01121')
        blok: 'biasa' (isian 27/28) atau 'usaha_2026' (isian 30/31)
        rasio_selancar: float rasio dari tabel Selancar (untuk cek toleransi G2)
        
    Returns:
        HasilEvaluasi (dict): {
            'status': 'APPLY' | 'SKIP' | 'NEED_REVIEW',
            'field': str | None,              # 'pbj', 'prod', atau 'ops' jika APPLY
            'nilai_lama': float | None,
            'nilai_baru': float | None,
            'rasio_lama': float,
            'rasio_baru': float | None,
            'alasan': str,
            'kode_catatan': str,              # '#1' jika APPLY
            'acuan_threshold': str,
            'operasi': str | None,
            'faktor': float | None
        }
    """
    pbj = float(nilai.get('pbj') or 0)
    prod = float(nilai.get('prod') or 0)
    ops = float(nilai.get('ops') or 0)
    beli = float(nilai.get('beli') or 0)
    kat = str(kategori or "G").upper().strip()
    kbli_str = str(kbli or "").strip()
    
    thresh = get_threshold(kat, kbli_str, skala="mikro_kecil")
    MIN_RATIO = thresh['min']
    MAX_RATIO = thresh['max']
    TARGET_RATIO = float(thresh.get('target') or ((MIN_RATIO + MAX_RATIO) / 2.0))
    THRESH_LEVEL = thresh['level']
    THRESH_LABEL = f"{THRESH_LEVEL} [{MIN_RATIO:.2f} - {MAX_RATIO:.2f}]"
    
    # G7: Kasus khusus semua biaya & pendapatan 0
    if pbj == 0 and prod == 0 and ops == 0 and beli == 0:
        return HasilEvaluasi({
            'status': 'NEED_REVIEW',
            'field': None,
            'nilai_lama': None,
            'nilai_baru': None,
            'rasio_lama': 0.0,
            'rasio_baru': None,
            'alasan': f"Semua nilai biaya & pendapatan 0 ({THRESH_LABEL}). Butuh konfirmasi lapangan.",
            'kode_catatan': "",
            'acuan_threshold': THRESH_LABEL,
            'operasi': None,
            'faktor': None
        })

    # Tugas Tambahan: Kasus PBJ = 0 tetapi pengeluaran ada
    # Imputasi pendapatan (PBJ) yang wajar sesuai rasio kategori agar tidak melonjak terlalu tinggi
    if pbj == 0 and (prod > 0 or ops > 0 or beli > 0):
        biaya_total = prod + ops
        aset_tanah = float(nilai.get('aset_tanah') or 0.0)

        # Skala target rasio: untuk pertanian (Kategori A), aset tanah besar mencerminkan kapasitas produksi & pendapatan lebih tinggi
        if kategori == 'A' and aset_tanah > 0:
            if aset_tanah >= 100_000_000:
                bobot_rentang = 0.65  # Aset tanah besar (kebun/peternakan komersial): target rasio tinggi
            elif aset_tanah >= 30_000_000:
                bobot_rentang = 0.50  # Aset tanah menengah
            else:
                bobot_rentang = 0.40  # Aset tanah kecil/pekarangan
        else:
            bobot_rentang = 0.40

        # Target rasio di dalam rentang threshold
        target_r = MIN_RATIO + (MAX_RATIO - MIN_RATIO) * bobot_rentang
        if target_r >= 0.95:
            target_r = 0.85
        elif target_r <= 0.05:
            target_r = 0.15

        # Hitung estimasi PBJ agar rasio mendekati target_r
        # Rasio = (PBJ - beli - biaya_total) / (PBJ - beli)
        estimasi_pbj = beli + (biaya_total / max(0.05, (1.0 - target_r)))

        # Bulatkan ke angka rapi (kelipatan 500rb atau 1jt)
        if estimasi_pbj < 5_000_000:
            step = 100_000
        elif estimasi_pbj < 50_000_000:
            step = 500_000
        else:
            step = 1_000_000

        pbj_kandidat = round(estimasi_pbj / step) * step

        # Verifikasi rasio hasil pembulatan masuk rentang
        out_cand = pbj_kandidat - beli
        if out_cand > 0:
            ntb_cand = out_cand - biaya_total
            r_cand = ntb_cand / out_cand
            while r_cand < MIN_RATIO:
                pbj_kandidat += step
                out_cand = pbj_kandidat - beli
                ntb_cand = out_cand - biaya_total
                r_cand = ntb_cand / out_cand
            while r_cand > MAX_RATIO and (pbj_kandidat - step - beli) > 0:
                pbj_kandidat -= step
                out_cand = pbj_kandidat - beli
                ntb_cand = out_cand - biaya_total
                r_cand = ntb_cand / out_cand
        else:
            r_cand = 0.0

        # Cek batas CAP_NILAI_BARU (250 jt skala tahunan)
        bulan_beroperasi = max(1, int(nilai.get('bulan_beroperasi') or 1))
        skala_faktor = bulan_beroperasi if blok == "usaha_2026" else 1
        val_skala = pbj_kandidat * skala_faktor

        if val_skala > CAP_NILAI_BARU:
            skala_txt = f" (skala tahunan: {int(val_skala):,})" if blok == "usaha_2026" else ""
            return HasilEvaluasi({
                'status': 'NEED_REVIEW',
                'field': None,
                'nilai_lama': 0.0,
                'nilai_baru': None,
                'rasio_lama': 0.0,
                'rasio_baru': None,
                'alasan': f"Estimasi PBJ ({int(pbj_kandidat):,}{skala_txt}) melebihi CAP_NILAI_BARU ({CAP_NILAI_BARU:,}) ({THRESH_LABEL}).",
                'kode_catatan': "",
                'acuan_threshold': THRESH_LABEL,
                'operasi': None,
                'faktor': None
            })

        if MIN_RATIO <= r_cand <= MAX_RATIO and pbj_kandidat > 0:
            aset_txt = f" & aset tanah {int(aset_tanah):,}" if aset_tanah > 0 else ""
            return HasilEvaluasi({
                'status': 'APPLY',
                'field': 'pbj',
                'nilai_lama': 0.0,
                'nilai_baru': float(pbj_kandidat),
                'rasio_lama': 0.0,
                'rasio_baru': r_cand,
                'alasan': f"Imputasi PBJ rasio wajar ({r_cand:.4f}): 0 -> {int(pbj_kandidat):,} berbasis total biaya {int(biaya_total):,}{aset_txt} ({THRESH_LABEL})",
                'kode_catatan': "#1",
                'acuan_threshold': THRESH_LABEL,
                'operasi': 'imputasi_wajar',
                'faktor': None
            })



    if pbj == 0 and prod == 0 and ops == 0 and beli == 0:
        return HasilEvaluasi({
            'status': 'NEED_REVIEW',
            'field': None,
            'nilai_lama': None,
            'nilai_baru': None,
            'rasio_lama': 0.0,
            'rasio_baru': None,
            'alasan': f"Semua nilai biaya & pendapatan 0 ({THRESH_LABEL}). Butuh konfirmasi lapangan.",
            'kode_catatan': "",
            'acuan_threshold': THRESH_LABEL,
            'operasi': None,
            'faktor': None
        })

    output = pbj - beli
    if output <= 0:
        return HasilEvaluasi({
            'status': 'NEED_REVIEW',
            'field': None,
            'nilai_lama': None,
            'nilai_baru': None,
            'rasio_lama': 0.0,
            'rasio_baru': None,
            'alasan': f"Output <= 0 (PBJ {pbj:,.0f} - Beli {beli:,.0f} = {output:,.0f}). Tidak dapat menghitung rasio ({THRESH_LABEL}).",
            'kode_catatan': "",
            'acuan_threshold': THRESH_LABEL,
            'operasi': None,
            'faktor': None
        })
        
    ntb = output - prod - ops
    rasio = ntb / output

    # G2: Bandingkan rasio hitungan FASIH dengan rasio_selancar (toleransi TOL_RASIO_SELANCAR = 0.02)
    if rasio_selancar is not None:
        selisih = abs(rasio - float(rasio_selancar))
        if selisih > TOL_RASIO_SELANCAR:
            return HasilEvaluasi({
                'status': 'NEED_REVIEW',
                'field': None,
                'nilai_lama': None,
                'nilai_baru': None,
                'rasio_lama': rasio,
                'rasio_baru': None,
                'alasan': f"Selisih rasio FASIH ({rasio:.4f}) vs Selancar ({float(rasio_selancar):.4f}) = {selisih:.4f} > {TOL_RASIO_SELANCAR}. Input tidak sama dengan Selancar ({THRESH_LABEL}).",
                'kode_catatan': "",
                'acuan_threshold': THRESH_LABEL,
                'operasi': None,
                'faktor': None
            })

    # G1: Jika rasio FASIH sudah dalam rentang threshold
    if MIN_RATIO <= rasio <= MAX_RATIO:
        # Kategori G: periksa juga COGS (Biaya Pembelian / Pendapatan) terhadap rentang KBLI.
        c_min, c_max = thresh.get('cogs_min'), thresh.get('cogs_max')
        if kat == "G":
            if c_min is not None and c_max is not None and pbj > 0:
                cogs = beli / pbj
                cogs_label = f"COGS {cogs:.4f} [{c_min:.4f} - {c_max:.4f}]"
                cogs_ok = (c_min <= cogs <= c_max)
            else:
                # Lampiran: "COGS rentang nol - tidak dipakai" -> cukup NTB/Output
                cogs_label = "COGS tidak dipakai untuk KBLI ini"
                cogs_ok = True
            if cogs_ok:
                # NTB/Output dan COGS sama-sama dalam rentang: tidak ada nilai yang diubah,
                # tetapi tetap diberi catatan #1 di FASIH dan Selancar ditandai 'sudah direvisi'.
                return HasilEvaluasi({
                    'status': 'SKIP',
                    'catat_saja': True,
                    'field': None,
                    'nilai_lama': None,
                    'nilai_baru': None,
                    'rasio_lama': rasio,
                    'rasio_baru': rasio,
                    'alasan': f"NTB/Output dan COGS sama-sama dalam rentang {THRESH_LABEL} (rasio: {rasio:.4f}; {cogs_label}). Hanya catatan #1, tanpa ubah nilai.",
                    'kode_catatan': "#1",
                    'acuan_threshold': THRESH_LABEL,
                    'operasi': None,
                    'faktor': None
                })
            # COGS di luar rentang: sesuaikan Biaya Pembelian (beli) supaya COGS masuk rentang
            # TANPA membuat NTB/Output keluar rentang.
            import math

            def _review_cogs(msg):
                return HasilEvaluasi({
                    'status': 'NEED_REVIEW',
                    'field': None,
                    'nilai_lama': None,
                    'nilai_baru': None,
                    'rasio_lama': rasio,
                    'rasio_baru': None,
                    'alasan': f"NTB/Output dalam rentang {THRESH_LABEL} (rasio: {rasio:.4f}) tetapi {cogs_label} di luar rentang. {msg}",
                    'kode_catatan': "",
                    'acuan_threshold': THRESH_LABEL,
                    'operasi': None,
                    'faktor': None
                })

            if beli <= 0:
                return _review_cogs("Biaya Pembelian 0, tidak dikarang otomatis (G4).")

            skala_b = max(1, int(nilai.get('bulan_beroperasi') or 1)) if blok == "usaha_2026" else 1
            biaya = prod + ops
            # Batas beli agar rasio NTB/Output tetap dalam rentang: pbj-beli ∈ [biaya/(1-MIN), biaya/(1-MAX)]
            b_lo = max(c_min * pbj, pbj - biaya / max(1e-9, 1.0 - MAX_RATIO), 0.0)
            b_hi = min(c_max * pbj, pbj - biaya / max(1e-9, 1.0 - MIN_RATIO))
            if b_lo >= b_hi:
                return _review_cogs("Tidak ada nilai Biaya Pembelian yang membuat COGS dan NTB/Output sama-sama dalam rentang.")

            lebar = b_hi - b_lo
            b0 = min(max(beli, b_lo + 0.1 * lebar), b_hi - 0.1 * lebar)   # perubahan sekecil mungkin, agak ke dalam rentang
            step = 50_000 if b0 < 1_000_000 else (100_000 if b0 < 10_000_000 else (500_000 if b0 < 50_000_000 else 1_000_000))
            b_new = float(round(b0 / step) * step)
            if b_new < b_lo or b_new > b_hi or b_new <= 0:
                b_new = float(round(b0))

            out_n = pbj - b_new
            cogs_n = b_new / pbj
            r_n = ((out_n - biaya) / out_n) if out_n > 0 else -1.0
            if not (out_n > 0 and c_min <= cogs_n <= c_max and MIN_RATIO <= r_n <= MAX_RATIO):
                return _review_cogs("Penyesuaian Biaya Pembelian tidak lolos verifikasi rentang.")
            if b_new > beli * 10 or b_new < beli / 10:
                return _review_cogs(f"Perubahan Biaya Pembelian ({int(beli):,} -> {int(b_new):,}) terlalu besar untuk otomatis.")
            if b_new > beli and b_new * skala_b > CAP_NILAI_BARU:
                return _review_cogs(f"Biaya Pembelian baru ({int(b_new):,}) melebihi CAP_NILAI_BARU ({CAP_NILAI_BARU:,}).")

            return HasilEvaluasi({
                'status': 'APPLY',
                'field': 'beli',
                'nilai_lama': beli,
                'nilai_baru': b_new,
                'rasio_lama': rasio,
                'rasio_baru': r_n,
                'alasan': f"Penyesuaian COGS: Biaya Pembelian {int(beli):,} -> {int(b_new):,} | COGS {beli / pbj:.4f} -> {cogs_n:.4f} [{c_min:.4f} - {c_max:.4f}] | NTB/Output {rasio:.4f} -> {r_n:.4f} ({THRESH_LABEL})",
                'kode_catatan': "#1",
                'acuan_threshold': THRESH_LABEL,
                'operasi': 'penyesuaian_cogs',
                'faktor': round(b_new / beli, 2)
            })
        return HasilEvaluasi({
            'status': 'SKIP',
            'field': None,
            'nilai_lama': None,
            'nilai_baru': None,
            'rasio_lama': rasio,
            'rasio_baru': rasio,
            'alasan': f"Sudah dalam rentang threshold {THRESH_LABEL} (rasio: {rasio:.4f}). Tidak perlu perbaikan.",
            'kode_catatan': "",
            'acuan_threshold': THRESH_LABEL,
            'operasi': None,
            'faktor': None
        })

    # Tugas 7: Skala bulanan vs tahunan untuk blok usaha 2026
    bulan_beroperasi = max(1, int(nilai.get('bulan_beroperasi') or 1))
    skala_faktor = bulan_beroperasi if blok == "usaha_2026" else 1

    # G3: Kandidat koreksi hanya salah-nol (x10 atau :10) pada tepat satu field (pbj, prod, ops)
    candidate_fields = ['pbj', 'prod', 'ops']
    valid_candidates = []
    cap_exceeded_candidates = []
    
    for f in candidate_fields:
        val = float(nilai.get(f) or 0)
        # G4: Field bernilai 0 atau kosong tidak boleh diubah
        if val <= 0:
            continue
            
        # Kandidat 1: val * FAKTOR_KALI (x10)
        new_val_kali = val * FAKTOR_KALI
        cand_pbj = new_val_kali if f == 'pbj' else pbj
        cand_prod = new_val_kali if f == 'prod' else prod
        cand_ops = new_val_kali if f == 'ops' else ops
        cand_beli = beli
        
        cand_out = cand_pbj - cand_beli
        if cand_out > 0:
            cand_ntb = cand_out - cand_prod - cand_ops
            cand_r = cand_ntb / cand_out
            if MIN_RATIO <= cand_r <= MAX_RATIO:
                # G6 & Tugas 7: Cap nilai baru untuk field yang DINAIKKAN
                # Harus dibandingkan pada skala yang sama dengan Selancar (tahunan)
                val_skala_selancar = new_val_kali * skala_faktor
                if val_skala_selancar > CAP_NILAI_BARU:
                    cap_exceeded_candidates.append({
                        'field': f,
                        'operasi': 'x10',
                        'nilai_lama': val,
                        'nilai_baru': new_val_kali,
                        'nilai_skala_selancar': val_skala_selancar,
                        'rasio_baru': cand_r
                    })
                else:
                    valid_candidates.append({
                        'field': f,
                        'operasi': 'x10',
                        'nilai_lama': val,
                        'nilai_baru': new_val_kali,
                        'rasio_baru': cand_r
                    })
                    
        # Kandidat 2: val / FAKTOR_BAGI (:10)
        # G4: :10 hanya jika nilai habis dibagi 10
        if int(val) % FAKTOR_BAGI == 0:
            new_val_bagi = val / FAKTOR_BAGI
            cand_pbj = new_val_bagi if f == 'pbj' else pbj
            cand_prod = new_val_bagi if f == 'prod' else prod
            cand_ops = new_val_bagi if f == 'ops' else ops
            cand_beli = beli
            
            cand_out = cand_pbj - cand_beli
            if cand_out > 0:
                cand_ntb = cand_out - cand_prod - cand_ops
                cand_r = cand_ntb / cand_out
                if MIN_RATIO <= cand_r <= MAX_RATIO:
                    valid_candidates.append({
                        'field': f,
                        'operasi': ':10',
                        'nilai_lama': val,
                        'nilai_baru': new_val_bagi,
                        'rasio_baru': cand_r
                    })

    # G5: Jika lolos >= 1 -> Pilih kandidat terbaik yang paling mendekati TARGET_RATIO dan langsung APPLY
    if len(valid_candidates) >= 1:
        best_candidate = min(valid_candidates, key=lambda c: abs(c['rasio_baru'] - TARGET_RATIO))
        c = best_candidate
        faktor_val = 10 if c['operasi'] == 'x10' else 0.1
        info_alt = f" [Dipilih otomatis dari {len(valid_candidates)} kandidat wajar]" if len(valid_candidates) > 1 else ""
        return HasilEvaluasi({
            'status': 'APPLY',
            'field': c['field'],
            'nilai_lama': c['nilai_lama'],
            'nilai_baru': c['nilai_baru'],
            'rasio_lama': rasio,
            'rasio_baru': c['rasio_baru'],
            'alasan': f"Koreksi salah-nol ({c['operasi']}) pada {c['field'].upper()}: {int(c['nilai_lama']):,} -> {int(c['nilai_baru']):,} | Rasio: {rasio:.4f} -> {c['rasio_baru']:.4f} ({THRESH_LABEL}){info_alt}",
            'kode_catatan': "#1",
            'acuan_threshold': THRESH_LABEL,
            'operasi': c['operasi'],
            'faktor': faktor_val
        })
    else:
        # Fallback jika salah-nol tidak masuk rentang: Penyesuaian wajar pengeluaran & pendapatan (PRD Update)
        # Menyesuaikan field secara proporsional mendekati TARGET_RATIO
        # Syarat ketat: Tidak tiba-tiba melonjak menjadi ratusan juta jika nilai awal tidak ratusan juta.
        def bulatkan_wajar(v):
            if v <= 0:
                return 0.0
            if v < 1_000_000:
                step = 50_000
            elif v < 10_000_000:
                step = 100_000
            elif v < 50_000_000:
                step = 500_000
            else:
                step = 1_000_000
            return float(round(v / step) * step)

        kandidat_wajar = []
        biaya_saat_ini = prod + ops

        # Skenario 1: Rasio di atas batas atas (rasio > MAX_RATIO, misal 0.95 vs max 0.94)
        # Biaya terlalu kecil -> Naikkan prod atau ops secara wajar
        if rasio > MAX_RATIO:
            target_biaya = output * (1.0 - TARGET_RATIO)
            # Coba sesuaikan PROD (baik prod > 0 maupun jika prod == 0 karena tidak mungkin biaya produksi 0)
            target_prod = max(50_000, target_biaya - ops)
            prod_bulat = bulatkan_wajar(target_prod)
            batas_atas_prod = max(prod * 6.0, 2_000_000) if prod > 0 else max(output * 0.5, 2_000_000)
            if prod_bulat <= batas_atas_prod and (prod < 50_000_000 and prod_bulat < 100_000_000) and (prod_bulat * skala_faktor <= CAP_NILAI_BARU):
                ntb_c = output - prod_bulat - ops
                r_c = ntb_c / output
                if MIN_RATIO <= r_c <= MAX_RATIO:
                    kandidat_wajar.append({
                        'field': 'prod',
                        'nilai_lama': prod,
                        'nilai_baru': prod_bulat,
                        'rasio_baru': r_c
                    })
            if ops > 0:
                target_ops = max(50_000, target_biaya - prod)
                ops_bulat = bulatkan_wajar(target_ops)
                if ops_bulat <= max(ops * 6.0, 1_000_000) and (ops < 50_000_000 and ops_bulat < 100_000_000) and (ops_bulat * skala_faktor <= CAP_NILAI_BARU):
                    ntb_c = output - prod - ops_bulat
                    r_c = ntb_c / output
                    if MIN_RATIO <= r_c <= MAX_RATIO:
                        kandidat_wajar.append({
                            'field': 'ops',
                            'nilai_lama': ops,
                            'nilai_baru': ops_bulat,
                            'rasio_baru': r_c
                        })

        # Skenario 2: Rasio di bawah batas bawah (rasio < MIN_RATIO)
        # Biaya terlalu besar -> Turunkan biaya, ATAU naikkan PBJ mendekati target (tanpa melonjak ke ratusan juta)
        elif rasio < MIN_RATIO:
            target_biaya = output * (1.0 - TARGET_RATIO)
            # A. Coba turunkan prod jika prod > ops
            if prod > 0 and target_biaya > ops:
                target_prod = target_biaya - ops
                prod_bulat = bulatkan_wajar(target_prod)
                if 0 < prod_bulat < prod and (prod_bulat * skala_faktor <= CAP_NILAI_BARU):
                    ntb_c = output - prod_bulat - ops
                    r_c = ntb_c / output
                    if MIN_RATIO <= r_c <= MAX_RATIO:
                        kandidat_wajar.append({
                            'field': 'prod',
                            'nilai_lama': prod,
                            'nilai_baru': prod_bulat,
                            'rasio_baru': r_c
                        })
            # B. Coba sesuaikan PBJ wajar (hanya jika pbj_bulat <= pbj * 3.5 dan tidak melonjak drastis ke ratusan juta)
            if biaya_saat_ini > 0 and pbj > 0 and rasio > -1.0:
                target_pbj_raw = beli + (biaya_saat_ini / max(0.05, (1.0 - TARGET_RATIO)))
                pbj_bulat = bulatkan_wajar(target_pbj_raw)
                if (pbj_bulat <= pbj * 3.5) and (pbj < 50_000_000 and pbj_bulat < 100_000_000) and (pbj_bulat * skala_faktor <= CAP_NILAI_BARU):
                    out_c = pbj_bulat - beli
                    if out_c > 0:
                        ntb_c = out_c - biaya_saat_ini
                        r_c = ntb_c / out_c
                        if MIN_RATIO <= r_c <= MAX_RATIO:
                            kandidat_wajar.append({
                                'field': 'pbj',
                                'nilai_lama': pbj,
                                'nilai_baru': pbj_bulat,
                                'rasio_baru': r_c
                            })

        if kandidat_wajar:
            best_w = min(kandidat_wajar, key=lambda c: abs(c['rasio_baru'] - TARGET_RATIO))
            f_val = round(best_w['nilai_baru'] / best_w['nilai_lama'], 2) if best_w['nilai_lama'] > 0 else None
            return HasilEvaluasi({
                'status': 'APPLY',
                'field': best_w['field'],
                'nilai_lama': best_w['nilai_lama'],
                'nilai_baru': best_w['nilai_baru'],
                'rasio_lama': rasio,
                'rasio_baru': best_w['rasio_baru'],
                'alasan': f"Penyesuaian wajar {best_w['field'].upper()}: {int(best_w['nilai_lama']):,} -> {int(best_w['nilai_baru']):,} | Rasio: {rasio:.4f} -> {best_w['rasio_baru']:.4f} ({THRESH_LABEL})",
                'kode_catatan': "#1",
                'acuan_threshold': THRESH_LABEL,
                'operasi': 'penyesuaian_wajar',
                'faktor': f_val
            })

        if cap_exceeded_candidates:
            c_cap = cap_exceeded_candidates[0]
            skala_info = f" (skala tahunan: {int(c_cap.get('nilai_skala_selancar', c_cap['nilai_baru'])):,})" if blok == "usaha_2026" else ""
            alasan = f"Kandidat koreksi {c_cap['field'].upper()} ({int(c_cap['nilai_lama']):,} -> {int(c_cap['nilai_baru']):,}{skala_info}) melebihi CAP_NILAI_BARU ({CAP_NILAI_BARU:,}) ({THRESH_LABEL})."
        else:
            alasan = f"Tidak ada kandidat koreksi wajar yang membuat rasio masuk rentang {THRESH_LABEL}. Rasio saat ini {rasio:.4f}."
            
        return HasilEvaluasi({
            'status': 'NEED_REVIEW',
            'field': None,
            'nilai_lama': None,
            'nilai_baru': None,
            'rasio_lama': rasio,
            'rasio_baru': None,
            'alasan': alasan,
            'kode_catatan': "",
            'acuan_threshold': THRESH_LABEL,
            'operasi': None,
            'faktor': None
        })



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
    # dan menyematkan remark catatan #1
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
                        'kode_catatan': "#1",
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
                            'kode_catatan': "#1",
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
                            'kode_catatan': "#1",
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
                        'kode_catatan': "#1",
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
                        'kode_catatan': "#1",
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
                        'kode_catatan': "#1",
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
                            'kode_catatan': "#1",
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
                        'kode_catatan': "#1",
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
                    'kode_catatan': "#1",
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
                    'kode_catatan': "#1",
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
                    'kode_catatan': "#1",
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
                    'kode_catatan': "#1",
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
                        'kode_catatan': "#1",
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
                        'kode_catatan': "#1",
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
                    'kode_catatan': "#1",
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
        # B2 fix: Konversi sqlite3.Row ke dict agar isinstance(row, dict) di calculate_usulan
        # berfungsi benar untuk membaca kategori dan kbli dari baris DB
        r_dict = dict(r)
        res = calculate_usulan(r_dict)
        
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

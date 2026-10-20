"""
test_evaluasi.py
Unit tests untuk kalkulator_usulan.evaluasi() sesuai PRD §11.
Mencakup 7 kasus utama PRD §11 + kasus khusus guardrail G1-G8.
"""

import unittest
from kalkulator_usulan import evaluasi
from config import CAP_NILAI_BARU, TOL_RASIO_SELANCAR


class TestEvaluasi(unittest.TestCase):
    def test_case_1_rasio_sudah_masuk_rentang_skip(self):
        """
        Kasus 1 (PRD §11): Rasio sudah masuk rentang -> SKIP, tidak ada perubahan
        (mereplikasi kasus 32 juta).
        """
        # Kategori A: rentang [0.51 - 0.94]
        # pbj = 32jt, prod = 6jt, ops = 2jt, beli = 0
        # rasio = (32 - 8) / 32 = 0.75 (dalam rentang)
        nilai = {'pbj': 32_000_000, 'prod': 6_000_000, 'ops': 2_000_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        self.assertEqual(res['status'], 'SKIP')
        self.assertIsNone(res['field'])
        self.assertIsNone(res['nilai_baru'])
        self.assertAlmostEqual(res['rasio_lama'], 0.75, places=2)
        self.assertIn("Sudah dalam rentang threshold", res['alasan'])

    def test_case_2_salah_nol_pbj_apply(self):
        """
        Kasus 2 (PRD §11): Salah-nol PBJ (mis. 3,2 jt jadi 32 jt) yang membuat
        rasio masuk rentang -> APPLY dengan satu field.
        """
        # Kategori A: rentang [0.51 - 0.94]
        # pbj = 3.2jt, prod = 6jt, ops = 2jt, beli = 0
        # rasio lama = (3.2 - 8) / 3.2 = -1.5 (di luar)
        # pbj * 10 = 32jt -> rasio = (32 - 8) / 32 = 0.75 (dalam rentang)
        nilai = {'pbj': 3_200_000, 'prod': 6_000_000, 'ops': 2_000_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        self.assertEqual(res['status'], 'APPLY')
        self.assertEqual(res['field'], 'pbj')
        self.assertEqual(res['nilai_lama'], 3_200_000)
        self.assertEqual(res['nilai_baru'], 32_000_000)
        self.assertAlmostEqual(res['rasio_baru'], 0.75, places=2)
        self.assertEqual(res['kode_catatan'], '#1')

    def test_case_3_dua_kandidat_dipilih_terbaik_apply(self):
        """
        Kasus 3: Dua kandidat sama-sama masuk rentang -> dipilih kandidat terbaik (paling mendekati TARGET_RATIO) dan APPLY.
        """
        # Kategori A: rentang [0.51 - 0.94], target ~0.725
        # pbj = 10jt, prod = 5jt, ops = 3jt, beli = 0
        # rasio awal = (10 - 8) / 10 = 0.20
        # Kandidat 1: pbj * 10 = 100jt -> rasio = (100 - 8) / 100 = 0.92 (|0.92 - 0.725| = 0.195)
        # Kandidat 2: prod / 10 = 500rb -> rasio = (10 - 3.5) / 10 = 0.65 (|0.65 - 0.725| = 0.075) -> Terbaik!
        nilai = {'pbj': 10_000_000, 'prod': 5_000_000, 'ops': 3_000_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        self.assertEqual(res['status'], 'APPLY')
        self.assertEqual(res['field'], 'prod')
        self.assertEqual(res['nilai_baru'], 500_000)
        self.assertAlmostEqual(res['rasio_baru'], 0.65, places=2)
        self.assertIn("Dipilih otomatis dari", res['alasan'])

    def test_case_4_cap_nilai_baru_exceeded_need_review(self):
        """
        Kasus 4 (PRD §11): Nilai baru PBJ lebih dari 250 jt -> NEED_REVIEW.
        """
        # Kategori A: rentang [0.51 - 0.94]
        # pbj = 30jt, prod = 50jt, ops = 20jt, beli = 0
        # pbj * 10 = 300jt (> CAP_NILAI_BARU 250jt)
        # rasio jika 300jt = (300 - 70) / 300 = 0.767 (masuk rentang jika tidak ada cap)
        nilai = {'pbj': 30_000_000, 'prod': 50_000_000, 'ops': 20_000_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        self.assertEqual(res['status'], 'NEED_REVIEW')
        self.assertIsNone(res['field'])
        self.assertIsNone(res['nilai_baru'])
        self.assertIn("CAP_NILAI_BARU", res['alasan'])

    def test_case_5_field_nol_tidak_diubah(self):
        """
        Kasus 5 (PRD §11): Field bernilai 0 tidak pernah diubah (tidak boleh dibuat dari nol).
        """
        # prod bernilai 0 tidak boleh diisi 30% PBJ atau dikali/dibagi
        nilai = {'pbj': 3_000_000, 'prod': 0, 'ops': 2_000_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        # Jika ada koreksi, hanya boleh pada pbj (3jt -> 30jt, rasio 28/30 = 0.933 masuk rentang)
        if res['status'] == 'APPLY':
            self.assertNotEqual(res['field'], 'prod')
        else:
            self.assertEqual(res['status'], 'NEED_REVIEW')

    def test_case_6_pbj_100k_prod_3jt_tidak_melonjak(self):
        """
        Kasus 6 (PRD §11): PBJ 100.000 dengan prod 3.000.000:
        TIDAK BOLEH menjadi 10.667.000 (tidak ada rumus karangan).
        Hasil harus NEED_REVIEW karena salah-nol tidak bisa menyelamatkan rasio ini.
        """
        nilai = {'pbj': 100_000, 'prod': 3_000_000, 'ops': 500_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        self.assertEqual(res['status'], 'NEED_REVIEW')
        self.assertIsNone(res['field'])
        self.assertIsNone(res['nilai_baru'])
        self.assertIn("Tidak ada kandidat", res['alasan'])

    def test_case_7_selisih_rasio_selancar_need_review(self):
        """
        Kasus 7 (PRD §11): Selisih rasio FASIH vs Selancar > 0.02 -> NEED_REVIEW.
        """
        # pbj = 32jt, prod = 6jt, ops = 2jt, beli = 0 -> rasio FASIH = 0.75
        # Selancar rasio = 0.50 (selisih 0.25 > 0.02)
        nilai = {'pbj': 32_000_000, 'prod': 6_000_000, 'ops': 2_000_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121', rasio_selancar=0.50)
        
        self.assertEqual(res['status'], 'NEED_REVIEW')
        self.assertIsNone(res['field'])
        self.assertIn("Selisih rasio FASIH", res['alasan'])

    def test_g7_pbj_nol_pengeluaran_ada_imputasi_wajar(self):
        """
        Sesuai instruksi: Jika PBJ = 0 tetapi pengeluaran ada, lakukan imputasi PBJ
        yang wajar berbasis total biaya dan rentang rasio kategori (tidak melonjak ratusan juta).
        """
        nilai = {'pbj': 0, 'prod': 1_000_000, 'ops': 500_000, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        self.assertEqual(res['status'], 'APPLY')
        self.assertEqual(res['field'], 'pbj')
        self.assertEqual(res['nilai_lama'], 0.0)
        # Total biaya 1.5jt, PBJ imputasi berkisar 4jt - 5jt, rasio masuk rentang A [0.51 - 0.94]
        self.assertGreater(res['nilai_baru'], 1_500_000)
        self.assertLess(res['nilai_baru'], 10_000_000)
        self.assertGreaterEqual(res['rasio_baru'], 0.51)
        self.assertLessEqual(res['rasio_baru'], 0.94)
        self.assertIn("Imputasi PBJ rasio wajar", res['alasan'])

    def test_kategori_a_aset_tanah_mempengaruhi_estimasi_pendapatan(self):
        """
        Pengujian Kategori A (Pertanian):
        Aset tanah besar (misal 150 juta) mencerminkan kapasitas produksi lebih besar,
        sehingga estimasi PBJ yang dihasilkan lebih tinggi daripada usaha dengan aset tanah kecil.
        """
        biaya = {'pbj': 0, 'prod': 3_000_000, 'ops': 1_000_000, 'beli': 0}
        
        # Kasus 1: Aset tanah kecil / nol
        nilai_kecil = {**biaya, 'aset_tanah': 5_000_000}
        res_kecil = evaluasi(nilai_kecil, kategori='A', kbli='01121')
        
        # Kasus 2: Aset tanah besar (150 juta)
        nilai_besar = {**biaya, 'aset_tanah': 150_000_000}
        res_besar = evaluasi(nilai_besar, kategori='A', kbli='01121')
        
        self.assertEqual(res_kecil['status'], 'APPLY')
        self.assertEqual(res_besar['status'], 'APPLY')
        # Estimasi PBJ untuk aset tanah besar harus lebih tinggi dari aset tanah kecil
        self.assertGreater(res_besar['nilai_baru'], res_kecil['nilai_baru'])
        # Rasio keduanya tetap dalam rentang Kategori A [0.51 - 0.94]
        self.assertGreaterEqual(res_besar['rasio_baru'], 0.51)
        self.assertLessEqual(res_besar['rasio_baru'], 0.94)
        self.assertIn("aset tanah", res_besar['alasan'])



    def test_g7_semua_nol(self):
        """
        Guardrail G7: Semua nilai 0 -> NEED_REVIEW.
        """
        nilai = {'pbj': 0, 'prod': 0, 'ops': 0, 'beli': 0}
        res = evaluasi(nilai, kategori='A', kbli='01121')
        
        self.assertEqual(res['status'], 'NEED_REVIEW')
        self.assertIn("Semua nilai biaya & pendapatan 0", res['alasan'])

    def test_tugas_7_blok_2026_rasio_sudah_masuk_rentang_skip(self):
        """
        Tugas 7: Blok usaha 2026, jika rasio bulanan FASIH sudah dalam rentang -> SKIP
        (mereplikasi kasus nyata 32 juta).
        """
        # pbj = 32jt, prod = 6jt, ops = 2jt, bulan_beroperasi = 12
        # rasio bulanan = (32 - 8) / 32 = 0.75 (dalam rentang A: 0.51 - 0.94)
        nilai = {'pbj': 32_000_000, 'prod': 6_000_000, 'ops': 2_000_000, 'beli': 0, 'bulan_beroperasi': 12}
        res = evaluasi(nilai, kategori='A', kbli='01121', blok='usaha_2026')
        
        self.assertEqual(res['status'], 'SKIP')
        self.assertIsNone(res['field'])
        self.assertIn("Sudah dalam rentang threshold", res['alasan'])

    def test_tugas_7_blok_2026_cap_skala_tahunan_exceeded(self):
        """
        Tugas 7: Batas CAP_NILAI_BARU (250 jt) pada usaha 2026 dibandingkan pada
        skala yang sama dengan Selancar (bulanan x bulan beroperasi).
        """
        # pbj = 3.2jt, prod = 6jt, ops = 2jt, bulan_beroperasi = 10
        # jika dinaikkan x10: pbj_baru = 32jt bulanan
        # pada skala tahunan Selancar: 32jt x 10 bulan = 320jt (> CAP 250jt)
        # Hasil harus NEED_REVIEW karena skala tahunan melebihi cap
        nilai = {'pbj': 3_200_000, 'prod': 6_000_000, 'ops': 2_000_000, 'beli': 0, 'bulan_beroperasi': 10}
        res = evaluasi(nilai, kategori='A', kbli='01121', blok='usaha_2026')
        
        self.assertEqual(res['status'], 'NEED_REVIEW')
        self.assertIsNone(res['field'])
        self.assertIn("CAP_NILAI_BARU", res['alasan'])
        self.assertIn("skala tahunan", res['alasan'])

    def test_tugas_7_blok_2026_koreksi_salah_nol_lolos_cap(self):
        """
        Tugas 7: Koreksi salah-nol pada usaha 2026 yang skala tahunannya di bawah cap -> APPLY.
        """
        # pbj = 200rb, prod = 400rb, ops = 100rb, bulan_beroperasi = 6
        # rasio awal = (0.2 - 0.5) / 0.2 = -1.5 (di luar)
        # pbj * 10 = 2jt -> rasio = (2 - 0.5) / 2 = 0.75 (dalam rentang A)
        # skala tahunan = 2jt * 6 = 12jt (< 250jt) -> lolos cap!
        nilai = {'pbj': 200_000, 'prod': 400_000, 'ops': 100_000, 'beli': 0, 'bulan_beroperasi': 6}
        res = evaluasi(nilai, kategori='A', kbli='01121', blok='usaha_2026')
        
        self.assertEqual(res['status'], 'APPLY')
        self.assertEqual(res['field'], 'pbj')
        self.assertEqual(res['nilai_baru'], 2_000_000)


class TestReadback(unittest.TestCase):
    """
    Unit tests untuk fungsi isi_field_dengan_readback (Guardrail G9 & Tugas 3).
    Menguji validasi kecocokan nilai input dan mekanisme pemulihan (rollback) jika terjadi mismatch.
    """
    def test_readback_sukses(self):
        from unittest.mock import MagicMock
        from eksekutor_fasih import isi_field_dengan_readback

        mock_page = MagicMock()
        mock_locator = MagicMock()
        # Saat dibaca ulang, input_value menghasilkan target yang diharapkan
        mock_locator.input_value.return_value = "32.000.000"

        sukses, clean_val = isi_field_dengan_readback(
            mock_page, mock_locator, nilai_baru=32_000_000, nilai_lama=3_200_000
        )
        self.assertTrue(sukses)
        self.assertEqual(clean_val, "32000000")

    def test_readback_mismatch_dan_restore(self):
        from unittest.mock import MagicMock, call
        from eksekutor_fasih import isi_field_dengan_readback

        mock_page = MagicMock()
        mock_locator = MagicMock()
        # Browser hanya menangkap sebagian karakter (mis. ada lag)
        mock_locator.input_value.return_value = "3.200"

        sukses, clean_val = isi_field_dengan_readback(
            mock_page, mock_locator, nilai_baru=32_000_000, nilai_lama=3_200_000
        )
        # Verifikasi kegagalan terdeteksi
        self.assertFalse(sukses)
        self.assertEqual(clean_val, "3200")

        # Verifikasi mekanisme pemulihan (restore nilai lama) dijalankan
        typed_calls = [c for c in mock_page.keyboard.type.call_args_list]
        self.assertGreaterEqual(len(typed_calls), 2)
        # Panggilan ketik terakhir harus berisi nilai lama
        self.assertEqual(typed_calls[-1][0][0], "3200000")


if __name__ == '__main__':
    unittest.main()


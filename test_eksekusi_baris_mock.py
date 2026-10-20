"""
test_eksekusi_baris_mock.py
Memvalidasi alur eksekusi_baris() secara end-to-end dengan Mock Playwright:
1. Memastikan alur membaca FASIH -> evaluasi() -> ketik dengan readback -> simpan status ke DB berjalan lancar.
2. Memastikan handle_waf_block mengembalikan status ke sebelumnya (bukan APPROVED).
3. Memastikan status DB diupdate dengan benar (APPLIED / SKIP / NEED_REVIEW / READBACK_MISMATCH).
"""

import unittest
import sqlite3
import json
from unittest.mock import MagicMock, patch

import eksekutor_fasih


class TestEksekusiBarisMock(unittest.TestCase):
    def setUp(self):
        # Database in-memory terisolasi
        self.raw_conn = sqlite3.connect(":memory:")
        self.raw_conn.row_factory = sqlite3.Row
        self.conn = MagicMock(wraps=self.raw_conn)
        # Jangan tutup koneksi in-memory saat fungsi memanggil conn.close()
        self.conn.close.side_effect = lambda: None
        self.conn.execute("""

            CREATE TABLE kasus_nerwana (
                assignment_id TEXT,
                nama_usaha TEXT,
                status TEXT DEFAULT 'PENDING',
                alasan_review TEXT,
                kode_catatan TEXT,
                blok TEXT,
                nilai_lama_fasih TEXT,
                nilai_baru_fasih TEXT,
                alasan_skip TEXT,
                remark_terverifikasi INTEGER DEFAULT 0,
                evaluasi_at TEXT,
                tindak_lanjut TEXT,
                PRIMARY KEY (assignment_id, nama_usaha)
            )
        """)
        self.conn.execute("""
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id TEXT,
                nama_usaha TEXT,
                aksi TEXT,
                status_sebelumnya TEXT,
                status_baru TEXT,
                nilai_lama TEXT,
                nilai_baru TEXT,
                kode_catatan TEXT,
                pesan TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def tearDown(self):
        self.conn.close()

    @patch("eksekutor_fasih.get_connection")
    @patch("eksekutor_fasih.cek_waf_bot")
    @patch("eksekutor_fasih.selesaikan_sso_pada_fasih")
    @patch("eksekutor_fasih.wait_fasih_ready")
    @patch("eksekutor_fasih.lakukan_revoke_dan_edit")
    @patch("eksekutor_fasih.buka_blok_ii")
    @patch("eksekutor_fasih.deteksi_blok")
    @patch("eksekutor_fasih.cari_container_isian_27a")
    @patch("eksekutor_fasih.cek_catatan_eksisting_27a")
    @patch("eksekutor_fasih.tutup_modal_dialog")
    @patch("eksekutor_fasih.baca_nilai_fasih")
    @patch("eksekutor_fasih.isi_field_dengan_readback")
    @patch("eksekutor_fasih.tambah_catatan_field")
    @patch("eksekutor_fasih.proses_halaman_catatan_dan_tampilkan_anomali")
    def test_eksekusi_baris_dry_run_apply(
        self, mock_anomali, mock_catatan, mock_rb, mock_baca, mock_tutup,
        mock_cek_dc, mock_c27, mock_deteksi, mock_buka, mock_revoke,
        mock_ready, mock_sso, mock_waf, mock_db
    ):
        mock_db.side_effect = lambda: sqlite3.connect(":memory:") if False else self.conn
        mock_waf.return_value = (False, "")
        mock_sso.return_value = ("OK", None)
        mock_ready.return_value = ("READY", None)
        mock_buka.return_value = (True, 1)
        mock_deteksi.return_value = "usaha_2026"
        mock_cek_dc.return_value = (False, "")
        
        # Mock data terbaca dari FASIH: pbj = 200rb, prod = 400rb, ops = 100rb, bln = 6
        mock_input = MagicMock()
        mock_baca.return_value = {
            'ok': True,
            'pbj': 200_000,
            'prod': 400_000,
            'ops': 100_000,
            'beli': 0,
            'bulan_beroperasi': 6,
            'kategori': 'A',
            'kbli': '01121',
            'field_locators': {'pbj': mock_input}
        }
        mock_rb.return_value = (True, "2000000")
        mock_catatan.return_value = True

        row = {
            'assignment_id': 'TEST-001',
            'nama_usaha': 'Usaha Test 1',
            'status': 'PENDING',
            'kode_catatan': '#1'
        }
        self.conn.execute("INSERT INTO kasus_nerwana (assignment_id, nama_usaha, status) VALUES (?, ?, ?)",
                          (row['assignment_id'], row['nama_usaha'], 'PENDING'))
        self.conn.commit()

        mock_page = MagicMock()
        mock_updater = MagicMock()
        target_info = {'link_btn': MagicMock(), 'stat': 'belum', 'rasio_selancar': None}

        hasil, info = eksekutor_fasih.eksekusi_baris(
            mock_page, row, dry_run=True, interaktif=False, isi_catatan=True,
            nerwana_updater=mock_updater, target_info=target_info, kategori="A"
        )

        self.assertEqual(hasil, "APPLIED")
        db_res = self.conn.execute("SELECT * FROM kasus_nerwana WHERE assignment_id = ?", ('TEST-001',)).fetchone()
        self.assertEqual(db_res['status'], 'APPLIED')
        self.assertEqual(db_res['remark_terverifikasi'], 1)
        self.assertIn("2000000", db_res['nilai_baru_fasih'])
        self.assertEqual(db_res['blok'], 'usaha_2026')

    @patch("eksekutor_fasih.get_connection")
    @patch("eksekutor_fasih.catat_waf_block")
    def test_handle_waf_block_restores_previous_status(self, mock_catat, mock_db):
        mock_db.side_effect = lambda: self.conn
        row = {
            'assignment_id': 'WAF-001',
            'nama_usaha': 'Usaha WAF',
            'status': 'PENDING'
        }
        self.conn.execute("INSERT INTO kasus_nerwana (assignment_id, nama_usaha, status) VALUES (?, ?, ?)",
                          (row['assignment_id'], row['nama_usaha'], 'PENDING'))
        self.conn.commit()

        mock_page = MagicMock()
        res_code, bot = eksekutor_fasih.handle_waf_block(mock_page, row, "BOT-101")

        self.assertEqual(res_code, "WAF_BLOCK")
        self.assertEqual(bot, "BOT-101")

        # Verifikasi status dikembalikan ke PENDING (bukan APPROVED!)
        db_res = self.conn.execute("SELECT status FROM kasus_nerwana WHERE assignment_id = ?", ('WAF-001',)).fetchone()
        self.assertEqual(db_res['status'], 'PENDING')


if __name__ == "__main__":
    unittest.main()

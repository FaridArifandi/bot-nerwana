# PRD & Implementation Plan: Refactor Bot Nerwana

**Proyek:** `D:\Work\2026\neraca\bot-nerwana` · **Pemilik:** Farid (BPS Kota Subulussalam) · **Tanggal:** 15 Oktober 2026 · **Status:** Draft siap dikerjakan agent

## 0. Aturan kerja untuk agent

- **Jangan jalankan mode SUBMIT SUNGGUHAN** (menu 2 dan 4 di `eksekutor_fasih.py`) saat mengembangkan atau menguji. Semua uji memakai DRY-RUN atau unit test.
- Jangan membaca, mencetak, atau meng-commit isi file `sso`.
- Backup `data_cleaning.db` ke folder `archive/` sebelum migrasi skema.
- Kerjakan berurutan per fase (bagian 9). Selesaikan dan uji satu fase sebelum lanjut.
- Jika selector FASIH belum jelas (blok usaha 2026, dialog Catatan), **berhenti dan minta dump HTML** (bagian 10). Jangan menebak selector.
- Semua angka ambang di bagian 6 harus berupa konstanta di satu file konfigurasi (`config.py`), bukan angka tersebar di kode.

## 1. Latar belakang

Bot mengotomasi koreksi data SE2026 yang terkena flag rasio NTB/Output di luar threshold. Alur saat ini:

1. Selancar Nerwana (tabel DC Terkena Flag): bot membaca atribut `data-*` tiap baris (`data-pbj`, `data-prod`, `data-ops`, dst.).
2. `calculate_usulan` menghitung nilai usulan dari atribut itu. Baris berstatus PENDING otomatis diubah menjadi APPROVED.
3. Bot membuka FASIH lewat Chrome CDP port 9222, revoke, masuk mode edit, mengisi nilai, menambah remark `#DC_01`, lalu mengirim.
4. Bot mengubah tindak lanjut di Selancar menjadi 'Sudah direvisi'.

File utama: `eksekutor_fasih.py`, `updater_nerwana.py`, `kalkulator_usulan.py`, `threshold_manager.py`, `database.py`, `sync_review.py`, `scraper_nerwana.py`, `master_threshold.json`. Stack: Python, Playwright, SQLite, openpyxl.

## 2. Masalah (dengan bukti)

### 2.1 Nilai melonjak atau turun terlalu jauh

- Kasus nyata: usaha baru beroperasi 2026 (pertanyaan 30-31), nilai dinaikkan dari sekitar Rp 32 juta menjadi sekitar Rp 400 juta, padahal di simulasi Selancar Rp 32 juta sudah masuk threshold.
- Dari `audit_log` (368 baris `SUBMIT_FASIH`, sampai 14 Okt 09:03): sekitar 20 baris PBJ naik 3x atau lebih. Contoh: tujuh baris kelapa sawit naik 19x sampai 106x (mis. Rp 100.000 menjadi Rp 10.667.000), beberapa baris naik tepat 10x, dan beberapa baris Kategori G naik lebih dari 3x.
- Sekitar 25 baris mengisi biaya produksi dari 0 menjadi 30% PBJ. Itu angka karangan, bukan data.
- Penyebab di kode: (a) di mode live semua usulan PENDING otomatis jadi APPROVED tanpa melihat skor; (b) jalur 'naikkan PBJ ke target rasio' dan 'turunkan proporsional' tidak punya batas; (c) pemilihan kandidat first-match.
- **Rumus bot sudah benar.** Diuji pada 3.405 baris `kasus_nerwana`: `output = pbj - beli`, `ntb = output - prod - ops`, `rasio = ntb / output` cocok 100% dengan kolom Selancar. Jadi masalahnya ada di **input**: atribut `data-*` Selancar untuk usaha 2026 tidak sama dengan isian FASIH yang sebenarnya.

### 2.2 Remark #DC\_01 tidak tersimpan

Data berubah tetapi remark tidak ada di FASIH, tanpa error. Penyebab di kode:

- `tambah_catatan_field` bersifat non-blocking. Jika tombol Catatan tidak ketemu, hanya mencetak 'dilewati', lalu bot tetap submit dan DB menulis `COMPLETED`.
- Container yang dioper berasal dari `cari_dan_isi_field`, yaitu div terkecil yang memiliki input. Tombol Catatan bisa berada di luar div itu.
- Tombol kirim di dialog dicari dengan `button:has(svg)` lalu `.last`. Itu bisa saja tombol tutup.
- Tidak ada verifikasi sesudah kirim.
- Untuk usaha 2026, keyword `'barang dan jasa'` bisa cocok dengan beberapa blok sehingga remark dan nilai bisa mendarat di blok yang salah.
- Catatan: 37 dari 368 baris audit `SUBMIT_FASIH` punya `kode_catatan` kosong. Kode memakai fallback `#DC_01`, jadi itu belum bukti remark gagal, tetapi tidak ada catatan yang membuktikan sebaliknya.

### 2.3 Bug pendukung

- `cek_kbli_kategori` selalu `return True` di akhir, sehingga cabang `KBLI_MISMATCH` tidak pernah jalan.
- `process_and_export` mengirim `sqlite3.Row` ke `calculate_usulan`, padahal pengecekan memakai `isinstance(row, dict)`, sehingga kategori dan KBLI jatuh ke default `'G'` dan kosong.
- Scraper meng-hardcode `kategori='A'` dan `kabkota=1175`.
- `skala='mikro_kecil'` di-hardcode untuk Kategori C.
- Pewarnaan Excel memakai rentang tetap 0,50-0,90 untuk semua kategori.

## 3. Tujuan dan non-tujuan

**Tujuan**

1. Selancar hanya menjadi antrean (menentukan baris berikutnya dan mengklik link). Angka tidak lagi diambil dari atribut Selancar.
2. Nilai awal dibaca langsung dari isian FASIH saat run, berdasarkan nomor pertanyaan.
3. Tidak ada lonjakan atau penurunan besar: bot hanya boleh mengoreksi salah-nol yang jelas, selain itu ditandai NEED\_REVIEW.
4. Remark `#DC_01` dijamin tersimpan dan terverifikasi sebelum submit.
5. Status 'Sudah direvisi' di Selancar dan `COMPLETED` di DB hanya ditulis setelah semuanya terverifikasi.

**Non-tujuan**

- Mengubah mekanisme login SSO, WAF circuit breaker, atau cooldown 30 menit (tetap seperti sekarang).
- Mengubah `master_threshold.json` atau `threshold_manager.py`.
- Membuat bot menebak nilai untuk kasus yang tidak punya indikasi salah ketik.

## 4. Alur baru per baris

1. **Selancar (antrean):** pilih baris pertama yang statusnya bukan `sudah_direvisi` atau `akan_direvisi`, tidak terkunci, dan statusnya di DB bukan salah satu dari COMPLETED, SKIP, NEED\_REVIEW, KBLI\_MISMATCH, FASIH\_FORBIDDEN, REMARK\_FAILED. Ambil `aid`, `nama`, `link_btn`, `tl_select`, `data_kunci`, dan `rasio_selancar` (hanya pembanding).
2. Ubah tindak lanjut menjadi 'Akan direvisi', buka tab FASIH lewat `link_btn` (logika SSO dan WAF tidak berubah).
3. Revoke dan masuk mode edit, buka Blok II, pilih usaha yang cocok.
4. **Deteksi blok:** usaha biasa (isian 27/28) atau usaha beroperasi 2026 (isian 30/31).
5. Cek remark DC eksisting di isian pendapatan. Jika sudah ada, tandai COMPLETED dan lanjut.
6. **Baca nilai dari FASIH** (`baca_nilai_fasih`) dan juga kategori serta KBLI dari isian 13.g dan 13.h. Jika ada yang tidak terbaca, NEED\_REVIEW.
7. **Evaluasi** (`kalkulator_usulan.evaluasi`) dengan nilai FASIH. Hasilnya SKIP, NEED\_REVIEW, atau APPLY (satu koreksi).
8. Jika SKIP atau NEED\_REVIEW: tutup tab tanpa kirim, kembalikan status Selancar ke semula, simpan status dan alasan di DB.
9. Jika APPLY: isi satu field, **baca ulang** dan bandingkan dengan target.
10. Tambah remark, **baca ulang dialog** dan pastikan ada `#DC_01`.
11. Halaman CATATAN: aktifkan switch 'Tampilkan Anomali Usaha dan Keluarga' (seperti sekarang).
12. Mode interaktif: tampilkan 'lama → baru' dan minta konfirmasi y/n.
13. Submit dan verifikasi.
14. Setelah semuanya terverifikasi: set 'Sudah direvisi' di Selancar, DB menjadi COMPLETED, tulis audit.

## 5. Functional requirements

| ID | Kebutuhan |
| --- | --- |
| FR-1 | `cari_target_di_tabel_selancar` tidak memanggil `calculate_usulan`, tidak meng-upsert APPROVED, dan tidak menulis SKIP atau NEED\_REVIEW berdasarkan atribut Selancar. |
| FR-2 | `deteksi_blok(page)` mengembalikan `'biasa'` atau `'usaha_2026'` berdasarkan nomor pertanyaan yang tampil. |
| FR-3 | `baca_nilai_fasih(page, blok)` mengembalikan dict `{pbj, prod, ops, beli}` (int) atau menandai field yang tidak terbaca. Field dicari berdasarkan nomor pertanyaan, bukan substring label. |
| FR-4 | `evaluasi(nilai, kategori, kbli, blok, rasio_selancar)` adalah fungsi murni (tanpa I/O) dan memakai `threshold_manager.get_threshold`. |
| FR-5 | `isi_field_by_nomor(page, nomor, nilai_baru)` mengetik, membaca ulang `input_value()`, dan mengembalikan `False` jika tidak sama persis. |
| FR-6 | `tambah_catatan_dan_verifikasi(page, field_ctx, kode)` bersifat blocking dengan retry 2 kali (bagian 7.3). |
| FR-7 | Setiap evaluasi menyimpan `nilai_lama_fasih`, `nilai_baru_fasih`, `blok`, `alasan` di DB dan audit log. |
| FR-8 | Mode DRY-RUN menjalankan seluruh alur kecuali tombol Kirim dan perubahan status Selancar. |

## 6. Aturan bisnis (guardrail)

Semua parameter ada di `config.py`.

| # | Aturan | Hasil jika dilanggar |
| --- | --- | --- |
| G1 | Hitung rasio dari nilai FASIH. Jika sudah dalam `[min, max]` threshold, jangan ubah apa pun. | `SKIP` |
| G2 | Bandingkan rasio hitungan dengan `rasio_selancar`. Selisih lebih dari `TOL_RASIO_SELANCAR = 0.02`. | `NEED_REVIEW` (alasan: input tidak sama dengan Selancar) |
| G3 | Kandidat koreksi hanya salah-nol: ×10 atau ÷10 pada **tepat satu** field (pbj, prod, atau ops; untuk usaha 2026 field 30 atau 31). Jalur 'naikkan ke target', 'turunkan proporsional', 'isi 30% PBJ' dihapus. | - |
| G4 | Field bernilai 0 atau kosong tidak boleh diubah (tidak boleh dibuat dari nol). ÷10 hanya jika nilai habis dibagi 10. | kandidat dibuang |
| G5 | Evaluasi semua kandidat. Hanya kandidat yang membuat rasio masuk rentang dan `output > 0` yang lolos. Jika lolos tepat satu, APPLY. Jika lebih dari satu (ambigu) atau nol, NEED\_REVIEW. | `NEED_REVIEW` |
| G6 | Nilai baru untuk field yang **dinaikkan** tidak boleh lebih dari `CAP_NILAI_BARU = 250_000_000`. | `NEED_REVIEW` |
| G7 | Kasus khusus yang sudah ada tetap: PBJ = 0 dengan biaya > 0, atau semua nilai 0, jadi NEED\_REVIEW. | `NEED_REVIEW` |
| G8 | Nilai lama di FASIH harus sama dengan nilai yang terbaca saat evaluasi. Jika data DB atau Excel ada dan berbeda, abaikan data DB itu. | `NEED_REVIEW` |
| G9 | Setelah mengetik, hasil baca ulang harus sama persis dengan target. Jika beda, ketik ulang nilai lama, jangan submit. | `READBACK_MISMATCH` |
| G10 | Remark harus terverifikasi sebelum submit. | `REMARK_FAILED` |
| G11 | Stop-loss: berhenti jika ada `MAX_ERR_BERTURUT = 3` error teknis berturut-turut (READBACK\_MISMATCH, REMARK\_FAILED, FAILED). NEED\_REVIEW dan SKIP bukan error teknis. | batch berhenti |
| G12 | `N_INTERAKTIF_AWAL = 10`: setelah update ini dirilis, 10 baris pertama yang di-submit wajib melalui konfirmasi y/n manual. | - |

Catatan prinsip: bila tidak ada indikasi salah ketik, lebih baik tidak mengubah angka dan menandai baris untuk konfirmasi lapangan.

## 7. Perubahan per file

### 7.1 `updater_nerwana.py`

- Pangkas `cari_target_di_tabel_selancar` menjadi filter antrean saja: lewati `sudah_direvisi`, `akan_direvisi`, terkunci, `session_skip_aids`, dan status DB final. Hapus blok `calculate_usulan`, upsert APPROVED, dan insert SKIP atau NEED\_REVIEW.
- Kembalikan juga `rasio_selancar` (dari `data-rasio`) sebagai pembanding.
- `set_tindak_lanjut_selancar` dan `NerwanaManager` tidak berubah.

### 7.2 `kalkulator_usulan.py`

- Tulis fungsi baru `evaluasi(...)` sesuai G1-G8. Hapus jalur 1b, 2d, 2e, 3e, 3f, 3g.
- Jangan membaca `row` yang bisa berupa `sqlite3.Row` atau dict: terima dict eksplisit.
- Kembalikan dict: `{status, field, nilai_lama, nilai_baru, rasio_lama, rasio_baru, alasan, kode_catatan, acuan_threshold}`.
- `process_and_export` dijadikan opsional untuk daftar NEED\_REVIEW (bagian 9, fase 4). Gunakan min dan max threshold per baris untuk pewarnaan, bukan 0,50-0,90.

### 7.3 `eksekutor_fasih.py`

- Fungsi baru: `deteksi_blok`, `baca_nilai_fasih`, `isi_field_by_nomor`, `tambah_catatan_dan_verifikasi`.
- Perbaiki `cek_kbli_kategori`: jika kategori tidak terbaca atau tidak cocok, kembalikan `False` (jangan `True`).
- **Perbaikan remark:**
  1. Temukan container dengan naik dari input pendapatan ke ancestor terdekat yang memuat `button[title='Catatan']`.
  2. Di dialog, cari tombol kirim di sekitar `textarea` (sibling atau dalam wrapper yang sama), bukan `button:has(svg)` terakhir. Fallback: Enter.
  3. Setelah kirim, tutup dan buka kembali dialog, baca teks, pastikan memuat `#DC_01`. Ulang maksimal 2 kali.
  4. Jika tetap gagal: jangan submit, tutup tab, status `REMARK_FAILED`, kembalikan status Selancar ke semula, tulis audit.
  5. Remark ditempel di isian pendapatan blok aktif (27a untuk usaha biasa, 31a untuk usaha 2026).
- Urutan: isi nilai, baca ulang, remark, verifikasi remark, halaman CATATAN, konfirmasi, submit, verifikasi, lalu sinkron ke Selancar.
- `eksekusi_baris` tidak lagi memakai `row['nilai_baru_*']` dari DB sebagai sumber utama. Nilai berasal dari `evaluasi` atas bacaan FASIH. Jika baris punya nilai dari Excel (status APPROVED), nilai itu hanya dipakai bila nilai lama di FASIH cocok (G8).
- Ganti `except Exception: pass` pada jalur kritis dengan log yang menyebut nama fungsi dan exception.

### 7.4 `database.py`

Migrasi aman (`ALTER TABLE ... ADD COLUMN`, nullable):

- `blok TEXT`, `nilai_lama_fasih TEXT` (JSON), `nilai_baru_fasih TEXT` (JSON), `alasan_skip TEXT`, `remark_terverifikasi INTEGER DEFAULT 0`, `evaluasi_at TIMESTAMP`.
- Status baru: `REMARK_FAILED`, `READBACK_MISMATCH`. Status `APPROVED` tetap ada hanya untuk jalur Excel opsional.
- Semua query ke `kasus_nerwana` memakai **kedua** kolom kunci `(assignment_id, nama_usaha)`.

### 7.5 `scraper_nerwana.py`

- Jadikan `kategori` dan `kabkota` parameter (bukan hardcode `'A'` dan `1175`). Prioritas rendah karena scraper tidak dipakai di alur live.

### 7.6 `sync_review.py`

- Tidak diubah di fase awal. Jika dipakai, nilai Excel hanya dieksekusi bila lolos G8 dan guardrail yang sama.

## 8. Status dan transisi

`(belum dievaluasi)` → `SKIP` | `NEED_REVIEW` | `APPLIED` (dry-run) | `COMPLETED` (submit dan remark terverifikasi) | `REMARK_FAILED` | `READBACK_MISMATCH` | `KBLI_MISMATCH` | `FASIH_FORBIDDEN` | `FAILED`.

Status 'Sudah direvisi' di Selancar hanya diset saat transisi menuju `COMPLETED`. Untuk status lain, tindak lanjut Selancar dikembalikan ke nilai semula.

Sediakan opsi menjalankan ulang evaluasi (`--reset-skip`) agar baris `SKIP` atau `NEED_REVIEW` bisa dievaluasi lagi jika data berubah.

## 9. Fase pengerjaan

**Fase 0: Hotfix aman (kerjakan dulu)**

- Perbaiki `cek_kbli_kategori`.
- Matikan auto-APPROVED di mode live (sementara: semua hasil heuristik lama jadi NEED\_REVIEW).
- Jadikan remark blocking: jika remark gagal, jangan submit.
- Perbaiki masalah `sqlite3.Row` vs dict.

**Fase 1: Pembaca FASIH dan kalkulator baru**

- `deteksi_blok` dan `baca_nilai_fasih` untuk **usaha biasa** (selector sudah ada di kode).
- `evaluasi` lengkap dengan G1-G8 dan unit test.
- Pangkas fungsi antrean Selancar.

**Fase 2: Remark dan verifikasi**

- Implementasi 7.3 poin remark, baca ulang nilai (G9), status baru, urutan sinkron.
- Perlu dump HTML dialog Catatan (bagian 10).

**Fase 3: Blok usaha 2026 (pertanyaan 30-31)**

- Setelah dump HTML dan definisi rasio dikonfirmasi (bagian 10).
- Pemetaan field per nomor pertanyaan dan uji DRY-RUN pada beberapa usaha 2026.

**Fase 4: Remediasi dan ekspor review**

- Skrip `audit_ulang.py` (bagian 12).
- Ekspor NEED\_REVIEW ke Excel (opsional).

## 10. Informasi yang masih dibutuhkan

Agent **tidak boleh menebak** hal berikut. Minta dari pemilik (Farid):

1. Dump HTML (`page.content()`) halaman Blok II untuk satu usaha biasa dan satu usaha beroperasi 2026.
2. Dump HTML dialog Catatan dalam keadaan terbuka (termasuk tombol kirim dan tombol tutup).
3. Label dan nomor pertanyaan pasti untuk: pendapatan, biaya produksi, biaya operasional, pembelian barang untuk dijual (Kategori G), di blok biasa dan blok 2026.
4. Apakah usaha 2026 memakai rumus rasio yang sama (`output = pbj - beli`, `ntb = output - biaya`) atau berbeda. Jika blok 2026 hanya punya satu isian pengeluaran, tentukan komponen mana yang boleh diubah.
5. Apakah FASIH menyimpan draf otomatis saat nilai diketik (menentukan apakah G9 harus mengembalikan nilai lama).
6. Skala usaha untuk Kategori C (`mikro_kecil` atau `besar_sedang`) bisa dibaca dari mana.

## 11. Pengujian dan kriteria penerimaan

**Unit test `evaluasi`**

- Rasio sudah masuk rentang: `SKIP`, tidak ada perubahan (mereplikasi kasus 32 juta).
- Salah-nol PBJ (mis. 3,2 jt jadi 32 jt) yang membuat rasio masuk rentang: `APPLY` dengan satu field.
- Dua kandidat sama-sama masuk rentang: `NEED_REVIEW`.
- Nilai baru PBJ lebih dari 250 jt: `NEED_REVIEW`.
- Field 0 tidak pernah diubah.
- PBJ 100.000 dengan prod 3.000.000: tidak boleh menjadi 10.667.000 (hasil harus NEED\_REVIEW atau hanya kandidat ×10 yang masuk rentang).
- Selisih rasio dengan Selancar lebih dari 0,02: `NEED_REVIEW`.

**Regresi rumus:** untuk semua baris `kasus_nerwana` dengan `output != 0`, `rasio_hitung == rasio` (toleransi 0,01). Saat ini 3.405 dari 3.405 cocok.

**Uji remark (dengan mock atau halaman uji):** remark terbaca ulang, retry bekerja, dan kegagalan membatalkan submit.

**DRY-RUN 20 baris, kriteria lolos:**

- Tidak ada perubahan dengan faktor selain 10 atau 0,1.
- Tidak ada nilai baru lebih dari 250 jt.
- 100% baris APPLY punya remark terverifikasi.
- Tidak ada baris dengan field 0 yang berubah.
- Setiap SKIP atau NEED\_REVIEW punya alasan terisi di DB.

## 12. Remediasi baris yang sudah submit

Skrip read-only `audit_ulang.py` (tidak mengubah FASIH, tidak revoke):

1. Dari `audit_log` (`action = 'SUBMIT_FASIH'`), keluarkan Excel daftar baris dengan: faktor perubahan PBJ 3x atau lebih, field yang naik dari 0, atau perubahan lebih dari satu field.
2. Untuk tiap baris, buka assignment hanya untuk **membaca** dialog Catatan isian pendapatan dan catat ada atau tidaknya `#DC_01`.
3. Output Excel: `assignment_id`, nama usaha, nilai lama, nilai baru, faktor, remark ada atau tidak, tautan FASIH, kolom keputusan manual.

Keputusan perbaikan data tetap manual oleh pemilik. Skrip ini hanya mengumpulkan daftar.

## 13. Risiko

- **Perubahan DOM FASIH** merusak selector. Mitigasi: pencarian berdasarkan nomor pertanyaan, readback, dan stop-loss G11.
- **Data pribadi responden** ikut ter-commit karena `data_cleaning.db` dan `review_usulan.xlsx` sengaja dikecualikan dari `.gitignore`. Pastikan repo privat dan batasi akses.
- **Konflik antar dua komputer** pada file biner DB. Mitigasi: tetap pakai `refresh_selancar_realtime` dan cek remark DC eksisting sebelum mengedit.

# 🤖 Bot Nerwana & Eksekutor FASIH SM

Otomatisasi pengolahan data flagging Selancar Nerwana BPS dan sinkronisasi koreksi kuesioner FASIH SM BPS berbasis Playwright (Python).

---

## 📋 Daftar Isi
- [Fitur Utama](#-fitur-utama)
- [Panduan Pemula: Setup Laptop Baru / Kosong (Tanpa Python & VS Code)](#-panduan-pemula-setup-laptop-baru--kosong)
  - [Langkah 1: Instalasi Python](#langkah-1-instalasi-python-di-laptop-baru)
  - [Langkah 2: Membuka Terminal di Folder Bot](#langkah-2-membuka-terminal-command-prompt-di-folder-bot)
  - [Langkah 3: Install Library Pendukung](#langkah-3-install-library-pendukung)
  - [Langkah 4: Konfigurasi Akun SSO BPS](#langkah-4-konfigurasi-akun-sso-bps)
- [Cara Menjalankan Bot](#-cara-menjalankan-bot)
  - [Metode A: Menggunakan Pintasan File Bat (Paling Praktis)](#metode-a-menggunakan-file-batch-paling-mudah)
  - [Metode B: Menggunakan Terminal / Command Prompt Manual](#metode-b-menggunakan-terminal--command-prompt-manual)
- [Menu & Mode Eksekusi](#-menu--mode-eksekusi)
- [Solusi Masalah Umum (Troubleshooting)](#-solusi-masalah-umum-troubleshooting)

---

## 🌟 Fitur Utama
1. **Pemeriksaan & Filter Data Nerwana**:
   - Terhubung langsung ke sesi browser Chrome aktif di halaman Selancar Nerwana.
   - Menyaring data *DC Terkena Flag* (Kategori A, C, G, dll.).
   - Mode Live On-the-Fly membaca urutan baris langsung dari tabel.
2. **Kalkulator & Heuristik Usulan Nilai**:
   - Rekonsiliasi otomatis nilai PBJ (Pengeluaran Barang dan Jasa), Produksi, dan Biaya Operasional sesuai formula validasi neraca.
3. **Eksekutor FASIH SM**:
   - Menangani pembukaan kuesioner, input angka secara natural (human-like typing), remark/catatan validasi, hingga auto-save/submit.
   - Dilengkapi *Circuit Breaker WAF* untuk mendeteksi batas request server dan auto-cooldown.

---

## 💻 Panduan Pemula: Setup Laptop Baru / Kosong
*(Khusus laptop yang belum terpasang Python, belum ada VS Code, dan dijalankan murni via Terminal / CMD)*

### Langkah 1: Instalasi Python di Laptop Baru
1. Unduh installer resmi Python untuk Windows:
   - Kunjungi situs resmi: [python.org/downloads](https://www.python.org/downloads/)
   - Disarankan mengunduh **Python versi 3.11 atau 3.12**.
2. **⚠️ SANGAT PENTING SAAT INSTALL:**
   - Jalankan file installer yang baru diunduh.
   - Pada halaman pertama installer, **WAJIB CENTANG** kotak:
     > **☑ Add python.exe to PATH** *(atau "Add Python to environment variables")*
   - Lalu klik **Install Now** dan tunggu hingga selesai.
3. Tutup installer setelah muncul pesan *Setup was successful*.

---

### Langkah 2: Membuka Terminal (Command Prompt) di Folder Bot
Anda **tidak perlu** menginstall VS Code. Cukup gunakan Command Prompt bawaan Windows:

1. Buka folder tempat file bot ini berada lewat **File Explorer** Windows.
2. Klik pada **Address Bar** di bagian atas jendela File Explorer (tempat tulisan path folder, misal `D:\Work\bot-nerwana`).
3. Ketik kata: `cmd` lalu tekan tombol **Enter**.
4. Jendela hitam Command Prompt (CMD) akan langsung terbuka tepat di dalam folder bot.
5. Uji apakah Python sudah terdeteksi dengan mengetik:
   ```cmd
   python --version
   ```
   *Jika muncul tulisan seperti `Python 3.12.x`, artinya Python sudah siap!*

---

### Langkah 3: Install Library Pendukung
Di jendela Command Prompt yang sama, jalankan dua perintah berikut secara berurutan:

1. **Install library Python:**
   ```cmd
   pip install -r requirements.txt
   ```
   *(Tunggu proses unduh hingga selesai bertuliskan Successfully installed)*

2. **Install browser Playwright:**
   ```cmd
   playwright install chromium
   ```
   *(Perintah ini akan mengunduh mesin browser Chromium yang dipakai bot)*

---

### Langkah 4: Konfigurasi Akun SSO BPS
Bot membutuhkan username dan password SSO BPS Anda untuk login otomatis ke FASIH.

1. Di dalam folder bot, cari file bernama `sso.example`.
2. Duplikat / copy file tersebut dan ubah namanya menjadi **`sso`** (tanpa ekstensi `.txt` atau `.example`).
   - *Via Terminal:* Anda cukup ketik perintah:
     ```cmd
     copy sso.example sso
     ```
3. Buka file `sso` menggunakan **Notepad**:
   - Ketik di terminal:
     ```cmd
     notepad sso
     ```
4. Ganti teks di dalamnya dengan akun SSO Anda:
   ```ini
   username=nama_pengguna_sso_anda
   password=kata_sandi_sso_anda
   ```
5. Tekan **Ctrl + S** untuk menyimpan, lalu tutup Notepad.

---

## 🚀 Cara Menjalankan Bot

Pastikan browser **Google Chrome** sudah terinstall di laptop Anda.

### Metode A: Menggunakan File Batch (Paling Mudah)
Di dalam folder bot sudah disediakan file bantuan yang bisa langsung diklik ganda:

1. **Klik ganda file `1_buka_chrome_debug.bat`**:
   - Jendela Google Chrome khusus (debug mode) akan terbuka otomatis.
   - **PENTING:** Jangan tutup jendela Chrome ini selama bot bekerja.
   - Di jendela Chrome tersebut, Anda bisa membuka tab baru dan pastikan sudah login/buka halaman **Selancar Nerwana**.
2. **Klik ganda file `2_jalankan_bot.bat`**:
   - Terminal eksekutor akan terbuka otomatis dan menampilkan menu pilihan.
   - Pilih menu yang diinginkan dengan mengetik angka lalu tekan Enter.

---

### Metode B: Menggunakan Terminal / Command Prompt Manual

Jika ingin menjalankan perintah sendiri dari terminal:

#### 1. Buka Google Chrome Mode Debug:
Buka satu jendela CMD, lalu jalankan:
```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="chrome_debug_profile" --start-maximized
```
*(Catatan: Jika Chrome terpasang di Program Files 32-bit, ganti menjadi `C:\Program Files (x86)\...`)*

#### 2. Jalankan Skrip Eksekutor:
Buka jendela CMD kedua di folder bot (lihat Langkah 2), lalu jalankan:
```cmd
python eksekutor_fasih.py
```

---

## ⚙️ Menu & Mode Eksekusi

Saat `eksekutor_fasih.py` berjalan, Anda akan diminta:
1. **Memilih Lapangan Usaha / Kategori:**
   - Masukkan kode huruf kategori, misal: `A`, `C`, `G`, dll.
2. **Memilih Mode Kerja:**
   - `[1] Uji 1 Baris Pertama - DRY-RUN` : Bot hanya mengisi angka di form FASIH untuk pengujian, **tanpa** menekan tombol submit.
   - `[2] Uji 1 Baris Pertama - SUBMIT SUNGGUHAN` : Bot mengisi form dan langsung melakukan **Submit** pada 1 sampel terpilih.
   - `[3] Eksekusi Batch DRY-RUN` : Menjalankan otomatis berurutan (bisa diset 1-10 baris) dalam mode simulasi/uji coba.
   - `[4] Eksekusi Batch SUBMIT SUNGGUHAN` : Menjalankan otomatis batch produksi dengan submit tersimpan ke server FASIH.

---

## ❓ Solusi Masalah Umum (Troubleshooting)

### 1. Pesan `'python' is not recognized as an internal or external command`
- **Penyebab:** Kotak *"Add python.exe to PATH"* lupa dicentang saat install Python.
- **Solusi:**
  1. Jalankan kembali file installer Python.
  2. Pilih menu **Modify**, lalu pastikan opsi **Add Python to environment variables** tercentang.
  3. Tutup dan buka kembali jendela Command Prompt (CMD).

### 2. Error `playwright._impl._errors.TargetClosedError` atau Browser Gagal Konek
- **Penyebab:** Google Chrome mode remote debugging belum dijalankan atau port 9222 tertutup.
- **Solusi:**
  1. Tutup seluruh aplikasi Google Chrome yang sedang aktif.
  2. Jalankan kembali `1_buka_chrome_debug.bat` (atau perintah manual remote-debugging).
  3. Pastikan jendela Chrome debug tetap terbuka di layar.

### 3. File `sso` berubah nama menjadi `sso.txt`
- **Penyebab:** Notepad otomatis menambahkan akhiran `.txt` jika ekstensi file disembunyikan Windows.
- **Solusi:**
  Buka CMD di folder bot, lalu jalankan perintah berikut untuk memastikan namanya tepat:
  ```cmd
  ren sso.txt sso
  ```

### 4. Eksekutor Terhenti / Ingin Berhenti di Tengah Jalan
- Untuk menghentikan bot yang sedang berjalan, klik pada jendela terminal bot lalu tekan kombinasi tombol:
  **`Ctrl + C`**

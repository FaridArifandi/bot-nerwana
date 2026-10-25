# 🤖 Bot Nerwana & Eksekutor FASIH SM

Otomatisasi pengolahan data flagging Selancar Nerwana BPS dan sinkronisasi koreksi kuesioner FASIH SM BPS berbasis Playwright (Python).

---

## 📋 Daftar Isi
- [Fitur Utama](#-fitur-utama)
- [Panduan Pemula: Setup Laptop Baru / Kosong (Tanpa Python & VS Code)](#-panduan-pemula-setup-laptop-baru--kosong)
  - [Langkah 1: Instalasi Python di Laptop Baru](#langkah-1-instalasi-python-di-laptop-baru)
  - [Langkah 2: Membuka Folder Bot di Terminal / CMD](#langkah-2-membuka-folder-bot-di-terminal-command-prompt)
  - [Langkah 3: Install Dependensi & Playwright (PENTING!)](#langkah-3-install-dependensi--playwright-penting)
  - [Langkah 4: Konfigurasi Akun SSO BPS](#langkah-4-konfigurasi-akun-sso-bps)
- [Cara Menjalankan Bot](#-cara-menjalankan-bot)
  - [Metode A: Menggunakan File Batch (Rekomendasi - Paling Praktis)](#metode-a-menggunakan-file-batch-rekomendasi---paling-praktis)
  - [Metode B: Menggunakan Terminal Manual](#metode-b-menggunakan-terminal--command-prompt-manual)
- [Panduan Khusus Rekan Tim (Update / Git Pull)](#-panduan-khusus-rekan-tim-update--git-pull)
- [Menu & Mode Eksekusi](#-menu--mode-eksekusi)
- [Solusi Masalah Umum (Troubleshooting)](#-solusi-masalah-umum-troubleshooting)

---

## 🌟 Fitur Utama
1. **Master Threshold Dinamis & Hierarkis**:
   - Terintegrasi langsung dengan Master Threshold resmi Selancar Nerwana.
   - Pengecekan rasio bertingkat: **KBLI 5-Digit** $\rightarrow$ **KBLI 3-Digit** $\rightarrow$ **KBLI 2-Digit** $\rightarrow$ **Kategori Utama (A - T)**.
   - Mendukung Kategori G (Perdagangan), Kategori A (Pertanian), Kategori C (Industri Pengolahan), dan seluruh sektor lainnya.
2. **Kalkulator & Heuristik Usulan Nilai**:
   - Menghitung koreksi nilai PBJ (Pengeluaran Barang dan Jasa), Produksi, dan Biaya Operasional secara presisi.
   - Kolom acuan threshold tercantum di Excel review (`review_usulan.xlsx`).
3. **Eksekutor FASIH SM (Playwright)**:
   - Terhubung langsung ke Chrome aktif (*remote debugging port 9222*).
   - Mode *Live On-The-Fly*: Menandai baris Selancar menjadi `'Akan direvisi'` sebelum membuka FASIH, lalu otomatis diubah ke `'Sudah direvisi'` setelah submit sukses.
   - Pengetikan natural (human-like typing), remark validasi `#DC_01`, serta proteksi *Circuit Breaker WAF*.

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

### Langkah 2: Membuka Folder Bot di Terminal (Command Prompt)
Anda **tidak perlu** menginstall VS Code. Cukup gunakan Command Prompt bawaan Windows:

1. Buka folder tempat file bot ini berada lewat **File Explorer** Windows.
2. Klik pada **Address Bar** di bagian atas jendela File Explorer (tempat tulisan path folder, misal `D:\Work\bot-nerwana`).
3. Ketik kata: `cmd` lalu tekan tombol **Enter**.
4. Jendela hitam Command Prompt (CMD) akan langsung terbuka tepat di folder bot.
5. Uji apakah Python sudah terdeteksi dengan mengetik:
   ```cmd
   python --version
   ```
   *Jika muncul tulisan seperti `Python 3.12.x`, artinya Python sudah aktif!*

---

### Langkah 3: Install Dependensi & Playwright (PENTING!)
Pada Windows, sering kali perintah `playwright` langsung tidak dikenali jika direktori Scripts belum masuk PATH. Oleh karena itu, **selalu gunakan awalan `python -m`**:

Jalankan 2 perintah berikut secara berurutan di CMD:

1. **Install library Python:**
   ```cmd
   python -m pip install -r requirements.txt
   ```
   *(Tunggu proses unduh library selesai)*

2. **Install browser Playwright (Chromium):**
   ```cmd
   python -m playwright install chromium
   ```
   > 💡 **Kenapa harus `python -m playwright`?**  
   > Supaya Windows langsung memanggil modul Playwright melalui Python secara resmi dan tidak muncul error `'playwright' is not recognized`.

*(Atau cukup klik ganda file `0_install_dependensi.bat`, file tersebut akan menjalankan kedua langkah di atas secara otomatis).*

---

### Langkah 4: Konfigurasi Akun SSO BPS
Bot membutuhkan username dan password SSO BPS Anda untuk login otomatis ke FASIH.

1. Di dalam folder bot, cari file bernama `sso.example`.
2. Salin (*copy*) file tersebut dan ubah namanya menjadi **`sso`** (tanpa ekstensi `.txt` atau `.example`).
   - *Via Terminal:* Cukup ketik perintah:
     ```cmd
     copy sso.example sso
     ```
3. Buka file `sso` menggunakan **Notepad**:
   ```cmd
   notepad sso
   ```
4. Ganti teks di dalamnya dengan akun SSO BPS Anda:
   ```ini
   username=nama_pengguna_sso_anda
   password=kata_sandi_sso_anda
   ```
5. Tekan **Ctrl + S** untuk menyimpan, lalu tutup Notepad.

---

## 🚀 Cara Menjalankan Bot

Pastikan browser **Google Chrome** sudah terinstall di laptop Anda.

### Metode A: Menggunakan File Batch (Rekomendasi - Paling Praktis)
Tinggal klik ganda file bantuan berurutan:

1. **Klik ganda `0_install_dependensi.bat`** (Hanya sekali saja saat pertama kali pasang di laptop baru).
2. **Klik ganda `1_buka_chrome_debug.bat`**:
   - Google Chrome khusus (mode remote debugging port 9222) akan terbuka.
   - **PENTING:** Jangan tutup jendela Chrome ini.
   - Buka tab baru di Chrome tersebut dan pastikan sudah login/buka halaman **Selancar Nerwana**.
3. **Klik ganda `2_jalankan_bot.bat`**:
   - Terminal eksekutor bot akan berjalan dan menampilkan menu interaktif.

---

### Metode B: Menggunakan Terminal / Command Prompt Manual

#### 1. Buka Google Chrome Mode Debug:
Buka satu jendela CMD, jalankan:
```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="chrome_debug_profile" --start-maximized
```

#### 2. Jalankan Skrip Eksekutor:
Buka jendela CMD kedua di folder bot, jalankan:
```cmd
python eksekutor_fasih.py
```

---

## 👥 Panduan Khusus Rekan Tim (Update / Git Pull)
Jika rekan kerja Anda sudah pernah mendownload repo ini dan ingin mengambil update terbaru (termasuk database dan review usulan terbaru):

1. Buka CMD di folder bot rekan Anda.
2. Jalankan:
   ```cmd
   git pull
   python -m playwright install chromium
   ```
3. Langsung jalankan bot seperti biasa (`2_jalankan_bot.bat` atau `python eksekutor_fasih.py`).

---

## 👥 Banyak Akun / Banyak Komputer

Satu repo ini bisa dipakai bersamaan oleh banyak akun, tiap orang di komputernya sendiri:

1. `git clone` repo ini, lalu klik ganda `0_install_dependensi.bat` (membuat file `sso` dari `sso.example`).
2. Isi `sso` dengan username & password SSO **akun sendiri** (file ini tidak ikut Git).
3. Klik `1_buka_chrome_debug.bat`, lalu `2_jalankan_bot.bat`.

- Wilayah (kabkota) dibaca otomatis dari akun yang login, tidak lagi tetap 1175.
- `data_cleaning.db` dibuat otomatis & lokal di tiap komputer (tidak di-commit). Status sebenarnya dibaca dari Selancar.
- Antar akun tidak berebut baris: baris yang `akan_direvisi`/terkunci oleh akun lain dilewati, dan urutan 8 baris teratas diacak.

---

## ⚙️ Menu & Mode Eksekusi

Saat `eksekutor_fasih.py` berjalan, Anda akan diminta:
1. **Memilih Lapangan Usaha / Kategori:**
   - `[1]` Kategori G - Perdagangan *(Master Threshold KBLI 5/3/2/Kat)*
   - `[2]` Kategori A - Pertanian *(Threshold 0.51 - 0.94)*
   - `[3]` Kategori C - Industri Pengolahan *(Master Threshold KBLI 2/Kat)*
   - *Atau ketik langsung huruf kategori lain: B, D, E, F, H, I, J, K, L, M, N, O, Q, R, S, T.*
2. **Memilih Mode Kerja:**
   - `[1] Uji 1 Baris Pertama - DRY-RUN` : Mengisi form FASIH untuk pengujian, **tanpa** submit.
   - `[2] Uji 1 Baris Pertama - SUBMIT SUNGGUHAN` : Mengisi form dan langsung submit 1 baris.
   - `[3] Eksekusi Batch DRY-RUN` : Menjalankan otomatis berurutan (1-50 baris) mode uji coba.
   - `[4] Eksekusi Batch SUBMIT SUNGGUHAN` : Menjalankan otomatis batch submit tersimpan ke server.

---

## ❓ Solusi Masalah Umum (Troubleshooting)

### 1. Pesan `'playwright' is not recognized as an internal or external command`
- **Penyebab:** Eksekutabel Playwright belum masuk ke PATH Windows.
- **Solusi:** Jalankan instalasi menggunakan modul Python secara eksplisit:
  ```cmd
  python -m playwright install chromium
  ```

### 2. Pesan `'python' is not recognized as an internal or external command`
- **Penyebab:** Opsi *"Add python.exe to PATH"* lupa dicentang saat install Python.
- **Solusi:** Jalankan installer Python kembali, pilih **Modify**, lalu centang **Add Python to environment variables**.

### 3. Error `TargetClosedError` / Gagal Terhubung ke Port 9222
- **Penyebab:** Google Chrome remote debugging belum dibuka sebelum bot dijalankan.
- **Solusi:** Tutup seluruh Google Chrome yang sedang aktif, lalu buka kembali lewat `1_buka_chrome_debug.bat`.

### 4. Menghentikan Bot
- Klik pada jendela terminal bot, lalu tekan kombinasi tombol: **`Ctrl + C`**.

# Bot Nerwana & Eksekutor FASIH

Otomatisasi pengolahan data flagging Selancar Nerwana BPS Aceh dan sinkronisasi kuesioner FASIH SM BPS berbasis Playwright (Python).

---

## 📋 Fitur Utama
1. **Pemeriksaan & Filter Data Nerwana**:
   - Menghubungkan browser Chrome debug ke halaman Selancar Nerwana (`/selancar2026/`).
   - Menyaring data *DC Terkena Flag* untuk Kategori A.
   - Pengecekan status pengerjaan (*sudah direvisi / terkunci*).
2. **Kalkulator & Heuristik Usulan Nilai**:
   - Rekonsiliasi nilai PBJ (Pengeluaran Barang dan Jasa), Produksi, dan Biaya Operasional sesuai aturan validasi.
3. **Eksekutor FASIH SM**:
   - Mendukung skenario **Revoke Assignment** maupun **Langsung Edit**.
   - Input angka natural dengan pengetikan keyboard acak untuk mencegah indikasi pola bot.
   - Penambahan kode remark/catatan validasi pada isian terkait.
   - Deteksi WAF circuit breaker otomatis (`.waf_lock` cooldown).
   - Pengelolaan sesi tab FASIH yang bersih setelah proses submit selesai.

---

## 🛠️ Instalasi & Persiapan

1. **Clone Repositori**:
   ```bash
   git clone https://github.com/FaridArifandi/bot-nerwana.git
   cd bot-nerwana
   ```

2. **Pasang Dependensi**:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Konfigurasi Akun SSO**:
   Salin file `sso.example` menjadi `sso`:
   ```bash
   cp sso.example sso
   ```
   Lalu isi username dan password SSO BPS Anda di dalam file `sso`:
   ```ini
   username=username_sso_anda
   password=password_sso_anda
   ```

---

## 🚀 Cara Menjalankan

1. **Jalankan Chrome dalam Mode Remote Debugging**:
   Buka Google Chrome dengan port debugging `9222`:
   ```powershell
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="chrome_debug_profile" --start-maximized
   ```

2. **Jalankan Skrip Eksekutor**:
   ```powershell
   python eksekutor_fasih.py
   ```
   Pilih mode yang diinginkan:
   - `[1]` Uji 1 Baris Pertama - DRY-RUN (Isi form tapi tidak submit).
   - `[2]` Uji 1 Baris Pertama - SUBMIT SUNGGUHAN.
   - `[3]` Eksekusi Batch DRY-RUN (Batas 1-10 baris).
   - `[4]` Eksekusi Batch SUBMIT SUNGGUHAN (Batas 1-10 baris).

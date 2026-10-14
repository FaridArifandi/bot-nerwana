import sqlite3

conn = sqlite3.connect('data_cleaning.db')
cursor = conn.cursor()

print("=== DISTRIBUSI STATUS USULAN ===")
cursor.execute("SELECT status, COUNT(*) FROM kasus_nerwana GROUP BY status")
for st, cnt in cursor.fetchall():
    print(f"  {st}: {cnt}")

print("\n=== DISTRIBUSI SKOR USULAN ===")
cursor.execute("SELECT skor_usulan, COUNT(*) FROM kasus_nerwana GROUP BY skor_usulan ORDER BY skor_usulan DESC")
for sk, cnt in cursor.fetchall():
    print(f"  Skor {sk}: {cnt}")

print("\n=== DISTRIBUSI KODE CATATAN ===")
cursor.execute("SELECT kode_catatan, COUNT(*) FROM kasus_nerwana GROUP BY kode_catatan")
for kc, cnt in cursor.fetchall():
    print(f"  {kc if kc else '(ditentukan saat review)'}: {cnt}")

cursor.execute("SELECT MIN(rasio_baru), MAX(rasio_baru), AVG(rasio_baru) FROM kasus_nerwana WHERE status = 'PENDING'")
min_r, max_r, avg_r = cursor.fetchone()
print(f"\nRasio Baru (kasus PENDING): min={min_r:.4f}, max={max_r:.4f}, avg={avg_r:.4f}")
conn.close()

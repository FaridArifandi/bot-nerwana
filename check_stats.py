import sqlite3

conn = sqlite3.connect('data_cleaning.db')
cursor = conn.cursor()

print("=== STATISTIK KASUS NERWANA ===")
total = cursor.execute("SELECT COUNT(*) FROM kasus_nerwana").fetchone()[0]
print(f"Total baris: {total}")

cursor.execute("SELECT tindak_lanjut, COUNT(*) FROM kasus_nerwana GROUP BY tindak_lanjut")
print("\nDistribusi Tindak Lanjut:")
for tl, count in cursor.fetchall():
    print(f"  {tl if tl else '(belum)'}: {count}")

cursor.execute("SELECT filter_spesifik, COUNT(*) FROM kasus_nerwana GROUP BY filter_spesifik ORDER BY COUNT(*) DESC LIMIT 10")
print("\nDistribusi Filter Spesifik:")
for fs, count in cursor.fetchall():
    print(f"  {fs}: {count}")

cursor.execute("SELECT MIN(rasio), MAX(rasio), AVG(rasio) FROM kasus_nerwana")
min_r, max_r, avg_r = cursor.fetchone()
print(f"\nRasio Range: min={min_r:.4f}, max={max_r:.4f}, avg={avg_r:.4f}")

out_threshold = cursor.execute("SELECT COUNT(*) FROM kasus_nerwana WHERE rasio < 0.51 OR rasio > 0.94").fetchone()[0]
in_threshold = cursor.execute("SELECT COUNT(*) FROM kasus_nerwana WHERE rasio >= 0.51 AND rasio <= 0.94").fetchone()[0]
print(f"Rasio di luar rentang (0.51 - 0.94): {out_threshold} baris")
print(f"Rasio di dalam rentang: {in_threshold} baris")
conn.close()

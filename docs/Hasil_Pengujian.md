# Hasil pengujian simulasi B-08

Tanggal: 1 Oktober 2026. Pengujian dilakukan pada Gazebo Harmonic 8.15, Python 3.10, dan rendering kamera Ogre2 melalui EGL. Ini pengujian fungsional dunia sintetis, bukan pengukuran akurasi perangkat keras atau model FOMO.

## Uji logika dan format

**13 pengujian pytest lulus.** Cakupan: arah mendekat/menjauh, lajur berbeda, sepeda diam, proyeksi jalur belok, kompensasi gravitasi ketika IMU miring, interpolasi dan putusnya GPS, deteksi benturan dan cooldown, persistensi antrean, pengiriman idempoten, penggabungan lokasi, deteksi dari piksel, dan penolakan koordinat tidak valid.

Validasi SDF (`gz sdf -k generated/capstone.sdf`) menghasilkan **Valid**. Plugin C++ berhasil dibangun, modul Python berhasil dikompilasi, dan pemeriksaan sintaks JavaScript lulus.

## Uji langsung di Gazebo

Rangkaian penerimaan menggerakkan sepeda melalui API kendali yang sama dengan dashboard. Sensor dan gambar berasal dari Gazebo aktif. Tidak ada laporan IMU atau flag vision yang disuntikkan untuk membuat skenario lulus.

| Skenario | Hasil aktual | Status |
| --- | --- | --- |
| Lubang baru A | Vision memperingatkan; satu laporan IMU tersimpan dan disinkronkan | Lulus |
| Mendekati B, vision dimatikan | Sumber buzzer DATABASE; satu observasi benturan | Lulus |
| Lajur sebelah B, vision dimatikan | Tidak ada buzzer; tidak ada laporan IMU baru | Lulus |
| Menjauhi B, vision dimatikan | Tidak ada buzzer; tidak ada laporan IMU baru | Lulus |
| Mendekati B dari arah balik | Sumber buzzer DATABASE; satu observasi benturan | Lulus |
| Lubang D saat offline | Vision memperingatkan; satu laporan IMU tersimpan lokal | Lulus |
| Antrean offline | Satu laporan tetap pending sebelum jaringan diaktifkan | Lulus |
| Online kembali | Antrean habis dan cache bertambah dari dua menjadi tiga titik dalam 1,39 detik | Lulus |

Bukti terstruktur tersimpan di `data/acceptance-final-evidence/summary.json`. Berkas JSON per skenario memuat status awal/akhir dan telemetri sampel; gambar JPEG menyimpan kamera saat peringatan dan setelah perjalanan. Database sesi uji ada di `data/acceptance-final/`. Hasil pengujian terdahulu disimpan terpisah dan tidak menjadi dasar tabel ini.

Kamera pada akhir enam skenario tercatat sekitar **15,1–15,2 FPS** waktu nyata. Untuk skenario A, peringatan vision pertama teramati ketika posisi referensi sepeda x ≈20,26 m, dengan perkiraan jarak kandidat visual 2,93 m. Peristiwa IMU kemudian tercatat sekitar 0,88 detik waktu simulasi setelah sampel peringatan tersebut. Angka ini menunjukkan urutan deteksi dalam satu lintasan, bukan batas latency atau statistik akurasi.

Rata-rata komputasi vision dalam lintasan A sekitar 0,88 ms per frame. Pengukuran tersebut hanya mencakup detektor/anotasi Python; transmisi gambar, polling dashboard, penjadwalan audio, dan speaker belum termasuk. Amplitudo IMU tidak boleh dipakai untuk mengkalibrasi perangkat fisik karena kontak roda model masih ideal.

## Uji browser dan kontrol

**Tujuh pemeriksaan browser lulus**, dicatat di `docs/browser-validation.json`: tidak ada error JavaScript, tampilan responsif tanpa overflow horizontal pada lebar 390 px, keyboard menggerakkan sepeda, tombol A membelokkan sepeda, Gamepad API menggerakkan sepeda, demo otomatis berfungsi dan berhenti saat fokus hilang, serta AudioContext aktif setelah tombol suara diklik. Tampilan desktop diperiksa pada 1440 × 1080 px.

Gamepad API diuji dengan input sintetis yang memakai pemetaan standar PS. Pengenalan USB/Bluetooth dan tombol pada stik PS fisik harus diperiksa pada perangkat pagelaran. AudioContext yang aktif membuktikan jalur audio browser dapat berjalan; volume dan bunyi dari speaker fisik belum diverifikasi.

## Mengulang pengujian

Gunakan **folder data baru** agar A dan D belum tersimpan sebagai lokasi dikenal. Jalankan dua terminal:

```bash
# Terminal 1
bash start.sh --headless --data-dir data/uji-baru-01

# Terminal 2, dari folder proyek
python3 -s -m pytest -q
python3 -s scripts/validate_demo.py --out data/bukti-uji-baru-01
```

Rangkaian integrasi mengubah posisi sepeda dan menambah laporan pada sesi tersebut. Jangan menggunakannya saat pengunjung sedang mengendalikan sepeda. Kinerja dan jitter dapat berubah sesuai hardware, driver, serta beban komputer.

Pengujian browser bersifat opsional dan tidak menjadi dependensi menjalankan simulator. Contoh setelah Playwright dan browser Chromium terpasang:

```bash
PLAYWRIGHT_MODULE=/path/node_modules/playwright \
PLAYWRIGHT_BROWSERS_PATH=/path/browser-cache \
BROWSER_DRIVE=1 node scripts/browser_check.cjs
```

## Yang belum dibuktikan

Pengujian ini belum membuktikan F1 vision 77%, sensitivitas IMU 80%, umur baterai, ketahanan cuaca, latency bunyi speaker fisik, dan perilaku GPS lapangan. Bobot FOMO belum diberikan sehingga OpenCV digunakan sebagai baseline demonstrasi. Bantuan propulsi, arah, dan keseimbangan adalah pengendali virtual untuk kemudahan penggunaan; bukan model lengkap biomekanika pesepeda.

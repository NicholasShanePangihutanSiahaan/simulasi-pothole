# Pengujian arena oval — 22 Oktober 2026

Pengujian memakai Gazebo Harmonic headless, Python sistem, dan server uji terpisah pada port 8785/8786. Database utama di `data/` tidak dihapus. Semua operasi reset dilakukan terhadap folder sementara `/tmp/pothole-oval-validation-v2` dan menghasilkan cadangan SQLite.

## Lingkup dan metode

- Dua lintasan lurus 160 m dan dua tikungan radius 30 m: panjang garis tengah 508,5 m, lebar 12 m.
- Paving 60 m atau 11,8% lintasan, retakan rambut, polisi tidur 8 cm, dan pothole A–D berkedalaman 9–17 cm.
- Sepeda benar-benar digerakkan melalui API kontrol; IMU, kamera, dan GPS berasal dari Gazebo, bukan injeksi hasil deteksi.
- Target kecepatan sekitar 3 m/s; kecepatan aktual berubah saat melewati cekungan dan tikungan.
- Skrip penerimaan: `scripts/validate_oval.py`; hasil tiap skenario memuat sampel sensor, posisi, jumlah laporan, dan foto kamera.

## Pemeriksaan logika

`/usr/bin/python3 -s -m pytest -q`: **24 uji lulus**. Cakupan meliputi arah/jalur peringatan, interpolasi GPS, kompensasi gravitasi, klasifikasi IMU dengan pitch, retakan tipis pada citra, deduplikasi, cadangan/reset persisten, seed setelah restart, penolakan sumber vision, dan geometri oval.

`gz sdf -k generated/capstone.sdf`: valid. Plugin C++ berhasil dibangun; pemeriksaan sintaks JavaScript dan kompilasi modul Python lulus.

## Integrasi sensor dan database

| Skenario | Hasil pada pengujian terbaru |
| --- | --- |
| Vision aktif, IMU mati, melewati A | Buzzer VISION aktif; 0 laporan |
| Pothole A dengan IMU dan vision | 1 laporan IMU; buzzer VISION |
| Retakan | 0 laporan; tidak ada buzzer vision |
| Polisi tidur | 0 laporan; tidak ada buzzer vision |
| Seluruh segmen paving 60 m | 0 laporan; tidak ada buzzer vision |
| Pothole B, vision mati | 1 laporan IMU |
| Pothole C kecil, lajur kiri | 1 laporan IMU; buzzer VISION |
| Mendekati B dari arah balik | Buzzer DATABASE |
| Pothole D saat offline | 1 laporan masuk antrean lokal |
| Reset saat masih offline | Server, cache, dan antrean kosong; cadangan dibuat |
| Mengaktifkan sinkronisasi setelah reset | Data lama tidak muncul kembali |
| Loop otomatis 220 detik simulasi | Melewati kedua tikungan dan kembali melewati garis start; peringatan database bekerja pada putaran berikutnya |

**12 pemeriksaan integrasi lulus.** Ringkasan mesin disimpan di `oval-validation.json`. Selama uji loop, kemiringan roll maksimum 0,0727 rad (sekitar 4,2°), ketinggian frame minimum 0,551 m, dan kamera pada akhir uji sekitar 15,1 FPS. Terdapat lima observasi IMU pada tiga lokasi tersinkron: A, B, dan D pada lajur kanan, lalu pengamatan ulang A dan B. C diuji terpisah pada lajur kiri.

## Browser dan restart

**8 pemeriksaan browser lulus** melalui Chromium/Playwright: JavaScript tanpa error, tata letak responsif, keyboard, kemudi, pemetaan Gamepad API sintetis, autopilot beserta heartbeat/berhenti saat blur, AudioContext, serta tombol reset database. Pembatalan dialog mempertahankan data; konfirmasi mengosongkan data. Bukti ringkas berada di `browser-validation.json`; tangkapan layar desktop dan mobile berada di `images/`.

Setelah reset dari tombol, launcher dihentikan lalu dijalankan lagi memakai folder data yang sama **tanpa --no-seed**. Sesi restart berjalan 18 detik lalu berhenti normal. Database device/server tetap memiliki 0 laporan, 0 cache, 0 hazard, dan 0 received; marker seed_initialized tetap 1. Titik contoh B tidak dimuat ulang. Semua proses uji sudah dihentikan.

## Perbaikan yang diverifikasi

Pengujian awal menemukan impuls palsu dari triangulasi kontak paving dan ketidakstabilan klasifikasi berbasis amplitudo saja. Kontak paving diganti dengan balok berseam sempit; klasifikasi runtime kini juga memeriksa arah perubahan pitch dari IMU. Kontur retakan yang terpotong batas bawah kamera ditangani dengan padding nol dan batas ketebalan/tinggi. Hasil uji awal sebelum perbaikan tidak dipakai sebagai bukti kelulusan versi akhir.

## Batas interpretasi

Ini pengujian demonstrasi pada dunia sintetis dan kecepatan sekitar 10–11 km/jam, bukan evaluasi statistik akurasi jalan nyata. Tidak menjamin bebas false positive/negative untuk semua kecepatan, pencahayaan, sudut melintas, atau perubahan parameter fisika. Vision masih OpenCV baseline, bukan bobot FOMO terlatih. Retakan merupakan visual rambut; kontak paving disederhanakan. Perangkat stik PS fisik, keterlambatan speaker nyata, dan perangkat IMU/GPS fisik belum diuji. Reset diserialisasi untuk satu perangkat simulator, bukan sistem multi-perangkat terdistribusi.

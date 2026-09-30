# Jaga Jalan — Simulasi Capstone B-08

Simulasi sepeda 3D di **Gazebo Harmonic** dengan kamera, IMU, GPS, kendali keyboard/stik PS, server HTTP, penyimpanan SQLite, dan dashboard lokal. Dibuat berdasarkan *B-08_Naskah Proposal C251 Final.pdf* serta alur yang diminta pengguna.

## Jalankan

Dari folder proyek:

```bash
bash start.sh
```

Buka **http://localhost:8765** di Firefox atau Chrome, tunggu sensor siap, lalu klik **Aktifkan suara**. Tidak memerlukan ROS, akun cloud, API key, unduhan peta, maupun internet saat demonstrasi. Server simulasi berjalan sebagai proses terpisah di port 8766.

```bash
bash start.sh --gui           # Tambahkan jendela Gazebo untuk melihat dunia dari sudut bebas
bash start.sh --headless      # Rendering EGL, cocok untuk pengujian tanpa jendela
bash start.sh --data-dir data/pagelaran-01  # Sesi database baru; data lama tetap ada
```

Hentikan dengan **Ctrl+C pada terminal launcher**. Database tetap tersimpan. Jangan menjalankan dua launcher pada port yang sama.

## Kendali

| Perangkat | Gerakan |
| --- | --- |
| Keyboard | W/↑ kayuh, A/← dan D/→ belok, S/↓ rem, spasi berhenti, Shift+S mundur |
| Stik PS standar | Analog kiri belok, R2 kayuh, L2 atau ✕ rem, △ kembali awal, Options demo otomatis |
| Dashboard | Demo otomatis, pemilihan skenario, sakelar sensor/jaringan, tombol kendali sentuh |

Klik area gambar/judul sebelum memakai keyboard. Kendali otomatis berhenti saat halaman kehilangan fokus atau tidak lagi mengirim input. Sambungkan stik melalui USB/Bluetooth OS, lalu tekan salah satu tombol. Pemetaan menggunakan Gamepad API standar; perangkat fisik belum diuji dalam pengerjaan ini.

## Alur yang didemonstrasikan

- **IMU → GPS → simpan lokal → server.** Akselerasi berasal dari sensor Gazebo saat roda bersentuhan dengan mesh jalan. GPS pada waktu benturan diinterpolasi dari dua sampel NavSat.
- **Vision → buzzer + LED.** Detektor OpenCV memproses piksel kamera depan dan memberi kotak deteksi. Kamera tidak membaca daftar lokasi lubang dari dunia.
- **Cache server + posisi + arah/jalur → buzzer + LED.** Lubang di belakang, lajur berbeda, terlalu jauh, atau saat sepeda diam tidak memicu peringatan peta.
- **Offline → antrean tersimpan → kirim ulang saat online.** Cache peta tetap tersedia. Laporan memiliki ID unik agar pengiriman ulang tidak menggandakan observasi; koordinat dekat digabung oleh server.

Lubang B merupakan satu titik contoh kontribusi pengguna lain yang sengaja dimuat ke server. A, C, dan D tidak dimasukkan ke database otomatis. Gunakan `--no-seed` dengan folder data baru untuk server kosong.

## Batas simulasi

Gerak vertikal, pitch, gravitasi, roda, dan kontak jalan dihitung Gazebo; propulsi, keseimbangan roll, dan arah dibantu pengendali pengendara virtual. Ini bukan model biomekanika pesepeda atau uji keselamatan kendaraan. Lingkungan berupa representasi kampus, bukan pemetaan lokasi UGM yang sesungguhnya.

**Bobot FOMO dari proposal belum disertakan.** Vision menggunakan baseline OpenCV untuk dunia sintetis. Hasil ini tidak membuktikan akurasi FOMO, akurasi sensor perangkat fisik, atau kinerja di jalan nyata. `pothole/vision.py` adalah titik penggantian detektor.

Secara default, IMU boleh menyimpan tanpa vision sesuai permintaan pengguna. Aktifkan **Kontrol & validasi lanjutan → Simpan hanya jika IMU + vision** untuk mendemonstrasikan validasi ganda proposal Bab 7. IMU sendiri mendeteksi anomali getaran; polisi tidur atau benturan lain dapat menyerupai lubang.

## Persyaratan

Lingkungan yang digunakan: Ubuntu 22.04, Gazebo Harmonic 8.15, Python 3.10, compiler C++17. Dependensi distribusi Ubuntu:

```bash
sudo apt install build-essential cmake pkg-config \
  python3-numpy python3-opencv python3-pil python3-reportlab python3-pytest
```

Gazebo perlu pustaka pengembangan `libgz-sim8-dev`, `libgz-plugin2-dev`, serta binding `python3-gz-transport13` dan `python3-gz-msgs10`. Ikuti [instalasi resmi Gazebo Harmonic](https://gazebosim.org/docs/harmonic/install_ubuntu/) bila Gazebo belum terpasang. Jangan mengganti instalasi ROS yang sudah ada; proyek ini memakai Gazebo Transport langsung.

Launcher memakai Python sistem (`/usr/bin/python3 -s`) agar paket Python pengguna tidak berbenturan dengan protobuf Gazebo. Kompilasi dan aset dibuat otomatis. GPU dengan dukungan OpenGL/EGL disarankan; performa sensor pada rendering software bergantung pada CPU.

## Panduan dan pengujian

Panduan lengkap tersedia di **[docs/Panduan_Simulasi_Capstone_B08.pdf](docs/Panduan_Simulasi_Capstone_B08.pdf)** dan [versi Markdown](docs/Panduan_Simulasi.md).

```bash
python3 -s -m pytest -q
gz sdf -k generated/capstone.sdf
python3 -s scripts/build_guide.py
```

Uji integrasi pada simulasi yang sedang berjalan (menggerakkan sepeda dan menambah data uji):

```bash
python3 -s scripts/check_live.py --scenario new --seconds 8
python3 -s scripts/check_live.py --scenario known --vision-off --seconds 7
python3 -s scripts/check_live.py --scenario last --offline --seconds 8
```

`config/demo.json` berisi parameter sensor/peringatan dan geometri lintasan. `data/` berisi database serta log; `generated/` berisi aset yang dapat dibuat ulang. Laporan pengujian terdapat di [docs/Hasil_Pengujian.md](docs/Hasil_Pengujian.md).

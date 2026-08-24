import modal

# ============================================================
# 1. & 3. Aşama: CPU İmajı — FFmpeg 7.1 Static Binary (3 Saniyede Hazır)
# ============================================================
image_cpu = (
    modal.Image.debian_slim()
    .apt_install("curl", "aria2", "rsync", "sshpass", "openssh-client", "xz-utils")
    .run_commands(
        "curl -fsSL https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o /tmp/ffmpeg.tar.xz && "
        "mkdir -p /tmp/ffmpeg-static && tar -xf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg-static --strip-components=1 && "
        "mv /tmp/ffmpeg-static/ffmpeg /usr/local/bin/ffmpeg && "
        "mv /tmp/ffmpeg-static/ffprobe /usr/local/bin/ffprobe && "
        "rm -rf /tmp/ffmpeg-static /tmp/ffmpeg.tar.xz"
    )
    .pip_install("requests", "fastapi[standard]", "psutil")
)

# ============================================================
# 2. Aşama: GPU İmajı — FFmpeg 7.1 KAYNAK DERLEME
# apt install ffmpeg çok eski (4.x) geliyor; scale_cuda:format 5.1+ gerektirir.
# Modal bu image'ı bir kez build edip cache'ler — sonraki deploy'lar anında olur.
# ============================================================
image_gpu = (
    modal.Image.from_registry("nvidia/cuda:12.2.0-devel-ubuntu22.04", add_python="3.11")
    .apt_install("curl", "ca-certificates")
    .run_commands(
        # 1. Derleme bağımlılıklarını kur
        "apt-get update -qq && apt-get install -y --no-install-recommends "
        "build-essential nasm yasm pkg-config libx264-dev libx265-dev libvpx-dev "
        "libopus-dev libmp3lame-dev libfdk-aac-dev libass-dev libfreetype6-dev "
        "curl xz-utils ca-certificates git",

        # 2. NVIDIA codec headers (NVENC API 12.1 - Modal L4 Driver Uyumlu)
        "git clone -b n12.1.14.0 --depth 1 https://github.com/FFmpeg/nv-codec-headers.git /tmp/nv-codec-headers && "
        "cd /tmp/nv-codec-headers && make install",

        # 3. FFmpeg 7.1 kaynak kodunu indir ve aç
        "curl -fsSL https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz -o /tmp/ffmpeg.tar.xz && "
        "mkdir -p /tmp/ffmpeg-src && tar -xf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg-src --strip-components=1",

        "export PATH=/usr/local/cuda/bin:$PATH LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH && "
        "cd /tmp/ffmpeg-src && ./configure "
        "--prefix=/usr/local "
        "--enable-gpl "
        "--enable-nonfree "
        "--enable-cuda-nvcc "
        "--enable-libnpp "
        "--enable-cuvid "
        "--enable-nvdec "
        "--enable-nvenc "
        "--enable-libx264 "
        "--enable-libx265 "
        "--enable-libvpx "
        "--enable-libopus "
        "--enable-libmp3lame "
        "--enable-libfdk-aac "
        "--enable-libass "
        "--enable-libfreetype "
        "--enable-shared "
        "--enable-pic "
        '--extra-cflags="-I/usr/local/cuda/include" '
        '--extra-ldflags="-L/usr/local/cuda/lib64" '
        '--nvccflags="-gencode arch=compute_75,code=sm_75 -O2" '
        "--disable-static "
        "--disable-debug "
        "--disable-doc",

        # 5. Derle, kur ve kütüphane yolunu güncelle
        "cd /tmp/ffmpeg-src && make -j$(nproc) && make install && ldconfig",

        # 6. Temizlik
        "rm -rf /tmp/ffmpeg-src /tmp/ffmpeg.tar.xz /tmp/nv-codec-headers",
    )
    .pip_install("requests", "fastapi[standard]", "psutil")
    .env({
        "PATH": "/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LD_LIBRARY_PATH": "/usr/local/cuda/lib64:/usr/local/lib"
    })
)

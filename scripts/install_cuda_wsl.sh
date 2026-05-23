#!/usr/bin/env bash
# CUDA for faster-whisper on WSL — no sudo required (pip wheels).
set -euo pipefail
cd "$(dirname "$0")/.."

echo "Installing NVIDIA CUDA 12 runtime libs via pip..."
python3 -m pip install -U "nvidia-cublas-cu12" "nvidia-cudnn-cu12" "nvidia-cuda-runtime-cu12" "nvidia-cuda-nvrtc-cu12"

echo ""
echo "Verifying libcublas.so.12..."
python3 -c "
from reels.cuda_env import setup_cuda_library_path, cuda_libs_available
dirs = setup_cuda_library_path()
print('LD_LIBRARY_PATH updated:', bool(dirs))
print('libcublas available:', cuda_libs_available())
if not cuda_libs_available():
    raise SystemExit(1)
print('OK — restart reels serve and run your job again.')
"

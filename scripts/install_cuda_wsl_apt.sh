#!/usr/bin/env bash
# Full CUDA toolkit on WSL (requires sudo password).
set -euo pipefail

echo "Installing NVIDIA CUDA repo + toolkit 12.6 for WSL Ubuntu..."
cd /tmp
wget -q https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get install -y cuda-toolkit-12-6 libcublas-12-6

if ! grep -q 'cuda/lib64' ~/.bashrc 2>/dev/null; then
  echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
  echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}' >> ~/.bashrc
fi

echo "Done. Run: source ~/.bashrc"
echo "Also run: bash scripts/install_cuda_wsl.sh  (pip libs for Python)"

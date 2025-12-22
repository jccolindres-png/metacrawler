sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3 python3-venv python3-pip
cd ~
pwd
mkdir metacrawler
mkdir clients
cd ~
ls
cd Metacrawler
cd metacrawler
unzip metacrawler.zip
sudo apt install unzip
unzip metacrawler.zip
cd
mkdir FileForgeAI
cd FileForgeAI
ls -
ls 
cd ~/FileForgeAI/Backend
python3 -m venv venv
source venv/bin/activate
python3 metacrawler/runner.py
python3 -m metacrawler.runner
pip install pyyaml
python3 -m metacrawler.runner
export PYTHONPATH=$(pwd)
python3 -m metacrawler.runner
touch config/__init__.py
python3 -m metacrawler.runner
cd ~/FileForgeAI/Backend
ls -l config
ls -l config/__init__.py
python3 -m metacrawler.runner
touch config/__init__.py
python3 -m metacrawler.runner
[200~cd ~/FileForgeAI  # o el directorio que contiene "Backend"
python3 -m Backend.metacrawler.runner~
cd ~/FileForgeAI  # o el directorio que contiene "Backend"
python3 -m Backend.metacrawler.runner
cd ~/FileForgeAI
python3 -m Backend.metacrawler.runner
cd ~/FileForgeAI/Backend
python3 metacrawler/runner.py
python3
ls -l ~/FileForgeAI/Backend
ls -l ~/FileForgeAI/Backend | grep config
find ~/FileForgeAI -name paths.py 2>/dev/null
find ~/FileForgeAI -name config -type d 2>/dev/null
python3 metacrawler/runner.py
ls -l ~/FileForgeAI/Backend
find ~/FileForgeAI -name config
cd ~/FileForgeAI python3 -m Backend.metacrawler.runner
cd ~/FileForgeAI
python3 -m Backend.metacrawler.runner
mkdir -p ~/fileforge-data 2
sudo chown -R ubuntu:ubuntu ~/fileforge-data
mkdir -p ~/fileforge-data
sudo chown -R ubuntu:ubuntu ~/fileforge-data
export FILEFORGE_INPUT_PDFS=~/fileforge-data/pdfs export FILEFORGE_CRAWLED_PDFS=~/fileforge-data/crawled_pdfs export FILEFORGE_OUTPUT_JSON=~/fileforge-data/json export FILEFORGE_LOGS=~/fileforge-data/logs export FILEFORGE_TMP=~/fileforge-data/tmp export METACRAWLER_ROOT=~/fileforge-data/metacrawler cd ~/FileForgeAI python3 -m Backend.metacrawler.runner
mkdir -p ~/fileforge-data
export FILEFORGE_INPUT_PDFS=~/fileforge-data/pdfs
export FILEFORGE_CRAWLED_PDFS=~/fileforge-data/crawled_pdfs
export FILEFORGE_OUTPUT_JSON=~/fileforge-data/json
export FILEFORGE_LOGS=~/fileforge-data/logs
export FILEFORGE_TMP=~/fileforge-data/tmp
export METACRAWLER_ROOT=~/fileforge-data/metacrawler
cd ~/FileForgeAI
python3 -m Backend.metacrawler.runner
pwd
ls Backend/metacrawler/config
ls Backend/metacrawler
cd ~/FileForgeAI/Backend
export PYTHONPATH=$(pwd)
python3 -m metacrawler.runner
find . -type f | grep -i url
cd ~/FileForgeAI/Backend
export PYTHONPATH=$(pwd)
python3 -m metacrawler.runner
python3 -m Backend.metacrawler.runner --log-level DEBUG
cat ~/FileForgeAI/Backend/metacrawler/runner.py
cat ~/FileForgeAI/Backend/metacrawler/utils/menu_utils.py
cat ~/FileForgeAI/Backend/metacrawler/utils/sources_utils.py
cd ~/FileForgeAI/Backend
export PYTHONPATH=$(pwd)
python3 -m metacrawler.bootstrap_sources
python3 -m metacrawler.runner
cd ~/FileForgeAI/Backend
python3 - << 'EOF'
import os
BASE_DIR = os.path.dirname(os.path.abspath("metacrawler/runner.py"))

paths = [
    os.path.join(BASE_DIR, "..", "clients"),
    os.path.join(BASE_DIR, "..", "..", "clients"),
    os.path.join(BASE_DIR, "..", "classifiers", "clients"),
    os.path.join(BASE_DIR, "..", "..", "classifiers", "clients"),
]

for p in paths:
    ap = os.path.abspath(p)
    print(ap, "=>", os.path.isdir(ap))
EOF

ls -la <ESE_PATH>
ls -la /home/ubuntu/FileForgeAI/Backend/classifiers/clients
find <ESE_PATH> -maxdepth 2 -type f
ls -la /home/ubuntu/FileForgeAI/Backend/clients
python3 -m metacrawler.runner

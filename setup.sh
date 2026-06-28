#!/bin/bash
# Vocalis Service Installation and Setup Script for Linux/Raspberry Pi

set -e

GREEN='\033[0;32m'
NC='\033[0;3m' # No Color
YELLOW='\033[1;33m'
RED='\033[0;31m'

echo -e "${GREEN}===============================================${NC}"
echo -e "${GREEN}  VOCALIS ASSISTANT SERVICE SETUP (LINUX)       ${NC}"
echo -e "${GREEN}===============================================${NC}"

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 was not found. Please install Python 3.11+ first.${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "Found Python version: ${PYTHON_VERSION}"

# 2. Setup virtual environment
echo -e "\n${GREEN}Step 1: Setting up Python Virtual Environment (.venv)...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "Virtual environment created."
else
    echo "Virtual environment already exists."
fi

# Activate virtual environment
source .venv/bin/activate

# 3. Upgrade pip & Install requirements
echo -e "\n${GREEN}Step 2: Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

# 4. Download ML Models
echo -e "\n${GREEN}Step 3: Downloading required ML models...${NC}"
python scripts/download_models.py

# 5. Create Systemd Service Configuration
echo -e "\n${GREEN}Step 4: Generating Systemd service configuration...${NC}"
PROJECT_DIR=$(pwd)
USER_NAME=$(whoami)

SERVICE_FILE="vocalis.service"

cat <<EOF > $SERVICE_FILE
[Unit]
Description=Vocalis Voice Assistant I/O Engine
After=network.target sound.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/python -m vocalis.main
Restart=always
RestartSec=5
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=vocalis
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo -e "Generated service file: ${PROJECT_DIR}/${SERVICE_FILE}"

echo -e "\n${GREEN}===============================================${NC}"
echo -e "${GREEN}  SETUP COMPLETE!                              ${NC}"
echo -e "${GREEN}===============================================${NC}"
echo -e "To register Vocalis as a background system service, run:"
echo -e "  ${YELLOW}sudo cp ${PROJECT_DIR}/${SERVICE_FILE} /etc/systemd/system/${NC}"
echo -e "  ${YELLOW}sudo systemctl daemon-reload${NC}"
echo -e "  ${YELLOW}sudo systemctl enable vocalis.service${NC}"
echo -e "  ${YELLOW}sudo systemctl start vocalis.service${NC}"
echo -e "\nTo check the logs of the service, run:"
echo -e "  ${YELLOW}journalctl -u vocalis.service -f${NC}"
echo -e "==============================================="

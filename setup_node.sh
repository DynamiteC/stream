#!/bin/bash

# setup_node.sh
# Usage: ./setup_node.sh [NODE_ID] [AWS_KEY] [AWS_SECRET] [BUCKET]
# Example: ./setup_node.sh node-05 AKIA... secret... my-bucket

set -e

# --- Configuration ---
# Pin versions to ensure stability across production fleet
DOCKER_COMPOSE_VERSION="v2.24.1"
# ---------------------

# 1. Variables
NODE_ID=${1:-"node-$(hostname)"}
AWS_KEY=$2
AWS_SECRET=$3
BUCKET=${4:-"my-streaming-platform"}
REPO_URL="https://github.com/your-org/streaming-platform.git" # Replace with actual

if [ -z "$AWS_KEY" ] || [ -z "$AWS_SECRET" ]; then
    echo "Error: AWS Credentials required."
    echo "Usage: ./setup_node.sh [NODE_ID] [AWS_KEY] [AWS_SECRET] [BUCKET]"
    exit 1
fi

echo ">>> Starting Setup for Node: $NODE_ID"

# 2. System Updates & Dependencies
echo ">>> Installing System Dependencies..."
sudo apt-get update -y
sudo apt-get install -y curl git

# Install Docker Engine (if not present)
if ! command -v docker &> /dev/null; then
    echo ">>> Installing Docker Engine..."
    # Using standard repo, but could use official script for stricter pinning
    sudo apt-get install -y docker.io
    sudo systemctl enable docker
    sudo systemctl start docker
else
    echo ">>> Docker Engine already installed. Skipping."
fi

# Install Docker Compose (Pinned Version)
if ! command -v docker-compose &> /dev/null; then
    echo ">>> Installing Docker Compose ${DOCKER_COMPOSE_VERSION}..."
    sudo curl -L "https://github.com/docker/compose/releases/download/${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    INSTALLED_VERSION=$(docker-compose version --short 2>/dev/null || echo "unknown")
    echo ">>> Docker Compose already installed ($INSTALLED_VERSION). Skipping."
fi

# 3. Code Setup
APP_DIR="/opt/streaming-node"
echo ">>> Setting up application in $APP_DIR..."

if [ -d "$APP_DIR" ]; then
    echo ">>> Directory exists, pulling latest..."
    cd $APP_DIR
    # git pull origin main  # Uncomment in production
else
    echo ">>> Cloning repository..."
    # git clone $REPO_URL $APP_DIR # Uncomment in production

    # For this template, we assume the script is run alongside the files
    # or the user manually copies them.
    # Creating placeholder directory if running purely from script
    sudo mkdir -p $APP_DIR
    sudo chown $USER:$USER $APP_DIR
    # In a real scenario, we would clone here.
fi

# 4. Configuration (.env)
echo ">>> Generating .env file..."
cd $APP_DIR

# Check if we are in the repo (presence of docker-compose.yml)
if [ ! -f "docker-compose.yml" ]; then
    echo "WARNING: docker-compose.yml not found. Assuming this script is running inside the repo root."
    # If script is run from root of repo, we are good.
fi

cat <<EOF > .env
NODE_ID=$NODE_ID
REGION=us-east-1
SECRET_KEY=$(openssl rand -hex 16)
S3_ENDPOINT=https://s3.example.com
S3_BUCKET=$BUCKET
AWS_ACCESS_KEY_ID=$AWS_KEY
AWS_SECRET_ACCESS_KEY=$AWS_SECRET
DRY_RUN=false
EOF

echo ">>> Configuration saved to .env"

# 5. Launch
echo ">>> Launching Services..."
# Ensure we use the binary we installed
/usr/local/bin/docker-compose up -d --build

echo ">>> Node $NODE_ID is READY!"
echo ">>> Stream to: rtmp://$(curl -s ifconfig.me)/live/streamKey"
echo ">>> Watch URL: http://$(curl -s ifconfig.me)/live/streamKey.mpd"
echo ">>> Health check: http://$(curl -s ifconfig.me)/health"

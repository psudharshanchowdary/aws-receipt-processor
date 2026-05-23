# Oracle Cloud Always-Free VM Deployment Guide

This guide details how to deploy this Docker compose receipt processor stack to an Oracle Cloud VM Instance in their Always-Free tier.

## 1. Create a Free Account
1. Sign up at [oracle.com/cloud/free](https://cloud.oracle.com/free).
2. Choose a Home Region near you.

## 2. Launch VM Instance
1. Go to **Compute** -> **Instances** -> **Create Instance**.
2. **Placement**: Keep default.
3. **Image and Shape**:
   - Click **Edit**.
   - Change Image to **Canonical Ubuntu 22.04** (Always-Free).
   - Change Shape to **Ampere** (ARM64) or **Specialty** (AMD x86 Always-Free).
4. **Networking**: Keep defaults (will create public IP).
5. **SSH Keys**: Download both the private and public keys.
6. Click **Create** and wait for VM to display "Running".

## 3. Configure Ingress Rules
1. Click on the VM Instance details -> click on **Virtual Cloud Network** link.
2. Click on the **Security List** -> **Add Ingress Rules**.
3. Add rules to open ports:
   - Port `3000` (Frontend UI)
   - Port `8000` (Flask API)
   - Port `8001` (DynamoDB Admin)

## 4. Install Docker on VM
Connect via SSH using your downloaded private key:
```bash
ssh -i /path/to/private_key.key ubuntu@<YOUR_VM_PUBLIC_IP>
```
Once connected, install Docker and Docker Compose:
```bash
sudo apt update
sudo apt install -y docker.io docker-compose
sudo usermod -aG docker $USER
newgrp docker
```

## 5. Clone and Deploy Stack
1. Clone your project code onto the VM.
2. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
3. Start the project stack in background mode:
   ```bash
   docker-compose up --build -d
   ```
4. Access the web interface at `http://<YOUR_VM_PUBLIC_IP>:3000`.

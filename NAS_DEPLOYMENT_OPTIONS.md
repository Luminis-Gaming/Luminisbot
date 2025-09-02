# 🚀 NAS Deployment Options for LuminisBot

You have **3 main options** for deploying LuminisBot on your NAS, depending on your preference and setup.

---

## 🎯 **Option 1: Git Repository (Recommended for Development)**

**Best for**: Active development, easy updates, full control

### Steps:
1. **Push your code to GitHub** (if not already done)
2. **On your NAS**:
   ```bash
   git clone https://github.com/PhilipAubert/LuminisBot.git
   cd LuminisBot
   cp .env.template .env
   nano .env  # Configure your credentials
   docker-compose up -d
   ```

### Pros:
✅ Easy updates with `git pull`  
✅ All files and documentation available  
✅ Can modify code locally on NAS  
✅ Version control and rollback capability  

### Cons:
❌ Requires Git on your NAS  
❌ Need to rebuild image on updates  

---

## 🎯 **Option 2: Pre-built Docker Image (Recommended for Production)**

**Best for**: Production deployment, minimal NAS storage, automatic updates

### Setup (One-time):
1. **From your current computer**, build and push the image:
   ```bash
   # Build the image
   docker build -t ghcr.io/philipaubert/luminisbot:latest .
   
   # Login to GitHub Container Registry
   echo $GITHUB_TOKEN | docker login ghcr.io -u PhilipAubert --password-stdin
   
   # Push the image
   docker push ghcr.io/philipaubert/luminisbot:latest
   ```

2. **Set up GitHub Actions** (already created!) to auto-build on code changes

### Deploy on NAS:
```bash
# One-liner deployment
curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/nas-deploy.sh | bash
```

Or manually:
```bash
# Download only the files you need
wget https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/docker-compose.prebuilt.yml -O docker-compose.yml
wget https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/.env.template -O .env.template

# Configure
cp .env.template .env
nano .env  # Add your credentials

# Deploy
docker-compose up -d
```

### Pros:
✅ Minimal files on NAS (just docker-compose.yml + .env)  
✅ Automatic builds via GitHub Actions  
✅ Fast deployment (no local building)  
✅ Easy to update (just pull new image)  

### Cons:
❌ Need Docker registry account  
❌ Less control over build process  

---

## 🎯 **Option 3: One-Command NAS Deployment**

**Best for**: Quick setup, no technical hassle

### Super Simple:
```bash
# Downloads everything and sets up automatically
bash <(curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/nas-deploy.sh)
```

This script will:
1. ✅ Download necessary files  
2. ✅ Create deployment directory  
3. ✅ Guide you through configuration  
4. ✅ Deploy the bot automatically  

---

## 🔧 **Comparison Table**

| Feature | Git Clone | Pre-built Image | One-Command |
|---------|-----------|-----------------|-------------|
| **Setup Complexity** | Medium | Medium | Easy |
| **NAS Storage** | Full repo | Minimal | Minimal |
| **Update Process** | `git pull` | `docker-compose pull` | Re-run script |
| **Customization** | Full | Limited | Limited |
| **Build Time** | Local build | No build | No build |
| **Dependencies** | Git + Docker | Docker only | Docker only |

---

## 🎯 **My Recommendation**

For your NAS deployment, I recommend **Option 2 (Pre-built Image)** because:

1. **Minimal files on NAS** - just docker-compose.yml and .env
2. **Automatic builds** - GitHub Actions builds new images when you push code
3. **Fast deployment** - no waiting for local builds
4. **Easy updates** - just `docker-compose pull && docker-compose up -d`

### Quick Start with Option 2:

1. **First, push your current code to GitHub**
2. **The GitHub Action will automatically build the image**
3. **On your NAS, run**:
   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/nas-deploy.sh)
   ```

That's it! Your bot will be running with automatic updates whenever you push new code. 🚀

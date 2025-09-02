# 🔧 Docker Build Troubleshooting Guide

## Common Build Issues and Solutions

### ❌ Issue: `Package 'libgdk-pixbuf2.0-0' has no installation candidate`

**Cause**: Package names have changed in newer Debian/Ubuntu versions

**Solutions**:

#### Option 1: Use Minimal Dockerfile (Recommended)
```bash
# Use the lightweight version without Chrome dependencies
docker-compose -f docker-compose.minimal.yml up -d --build
```

#### Option 2: Use Pre-built Image (Easiest)
```bash
# Download and use pre-built image (no local building)
wget https://raw.githubusercontent.com/PhilipAubert/LuminisBot/main/docker-compose.prebuilt.yml -O docker-compose.yml
docker-compose up -d
```

#### Option 3: Fix Full Dockerfile
The updated Dockerfile now includes fallback logic for package installation.

---

### ❌ Issue: Chrome/Browser Dependencies Failing

**Cause**: Your bot might not need browser automation

**Check**: Does your code use Selenium or webdriver-manager?
- If **NO**: Use `Dockerfile.minimal` and `requirements.minimal.txt`
- If **YES**: Use the full Dockerfile with Chrome

**Solution for Minimal Setup**:
```bash
# Copy minimal requirements
cp requirements.minimal.txt requirements.txt

# Use minimal docker-compose
docker-compose -f docker-compose.minimal.yml up -d --build
```

---

### ❌ Issue: Build Takes Too Long / Runs Out of Memory

**Solutions**:

1. **Use Pre-built Image** (no building required):
   ```bash
   docker-compose -f docker-compose.prebuilt.yml up -d
   ```

2. **Increase Docker Memory Limits** in your NAS Docker settings

3. **Use Multi-stage Build** (already implemented in Dockerfiles)

---

### ❌ Issue: `docker: command not found`

**Cause**: Docker not installed on your system

**Solutions**:
1. **Install Docker** on your NAS
2. **Use a different machine** to build and push the image
3. **Use pre-built images** (recommended)

---

## 🎯 Recommended Deployment Strategy

### For Most Users (Easiest):
```bash
# One-command deployment with pre-built image
bash <(curl -fsSL https://raw.githubusercontent.com/PhilipAubert/LuminisBot/main/nas-deploy.sh)
# Choose option 1 (pre-built image)
```

### For Advanced Users (Full Control):
```bash
# Clone repository and build locally
git clone https://github.com/PhilipAubert/LuminisBot.git
cd LuminisBot
cp .env.template .env
nano .env  # Configure your settings

# Try builds in order of preference:
# 1. Minimal build (fastest)
docker-compose -f docker-compose.minimal.yml up -d --build

# 2. Full build (if you need Chrome features)
docker-compose up -d --build

# 3. Pre-built image (if builds fail)
docker-compose -f docker-compose.prebuilt.yml up -d
```

---

## 🔍 Debugging Build Issues

### View Build Logs:
```bash
docker-compose build --no-cache
```

### Test Package Installation:
```bash
# Test if packages are available
docker run --rm python:3.11-slim apt list libgdk-pixbuf*
```

### Check Available Images:
```bash
# See what images are available
docker images | grep luminisbot
```

### Clean Build Cache:
```bash
# Clean up and retry
docker system prune -a
docker-compose build --no-cache
```

---

## 📋 File Comparison

| File | Purpose | Chrome Support | Build Time |
|------|---------|----------------|------------|
| `Dockerfile` | Full featured | ✅ Yes | Slow |
| `Dockerfile.minimal` | Lightweight | ❌ No | Fast |
| `docker-compose.yml` | Full build | ✅ Yes | Local build |
| `docker-compose.minimal.yml` | Minimal build | ❌ No | Local build |
| `docker-compose.prebuilt.yml` | Pre-built | ✅ Yes | No build |

---

## 🎯 Quick Fix Commands

```bash
# If current build fails, try minimal:
docker-compose -f docker-compose.minimal.yml up -d --build

# If minimal fails, use pre-built:
wget https://raw.githubusercontent.com/PhilipAubert/LuminisBot/main/docker-compose.prebuilt.yml -O docker-compose.yml
docker-compose up -d

# If everything fails, one-liner:
bash <(curl -fsSL https://raw.githubusercontent.com/PhilipAubert/LuminisBot/main/nas-deploy.sh)
```

Your bot will work the same regardless of which method you choose! 🚀

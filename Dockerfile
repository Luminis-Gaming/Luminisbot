# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# --- Install system dependencies ---
# Install basic system packages (compatible with different Debian versions)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    curl

# Add Google Chrome repository
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg \
    && echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main' > /etc/apt/sources.list.d/google-chrome.list

# Install Chrome and core dependencies with error handling
RUN apt-get update && apt-get install -y google-chrome-stable || \
    (echo "Warning: Chrome installation failed, but bot will work without it" && true)

# Install Chrome runtime dependencies (with fallbacks for different Debian versions)
RUN apt-get install -y \
    libnss3 \
    libxss1 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libasound2 \
    libdrm2 \
    libxrandr2 \
    fonts-liberation \
    xdg-utils \
    2>/dev/null || echo "Some Chrome dependencies not available - continuing"

# Try to install additional Chrome dependencies
RUN apt-get install -y libatk-bridge2.0-0 2>/dev/null || \
    apt-get install -y libatk-bridge-2.0-0 2>/dev/null || \
    echo "Warning: libatk-bridge not available"

# Try to install libgdk-pixbuf with fallback options
RUN apt-get install -y libgdk-pixbuf-xlib-2.0-0 || \
    apt-get install -y libgdk-pixbuf2.0-0 || \
    echo "Warning: Could not install libgdk-pixbuf package - continuing without it"

# Clean up apt cache
RUN rm -rf /var/lib/apt/lists/*

# --- Install Python dependencies ---
# Copy the requirements file first to leverage Docker's layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# --- Environment Configuration ---
# Set environment variables for containerized operation
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash luminisbot
RUN chown -R luminisbot:luminisbot /app
USER luminisbot

# Expose the Flask keep-alive port
EXPOSE 10000

# --- Define the command to run your bot ---
# This will be run automatically when the container starts
CMD ["python", "my_discord_bot.py"]
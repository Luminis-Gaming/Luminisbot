# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# --- Install system dependencies ---
# Install Google Chrome, curl for health checks, and other dependencies
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates curl \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg \
    && echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main' > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable libnss3 libxss1 libgdk-pixbuf2.0-0 libgtk-3-0 libx11-xcb1 \
    # Clean up apt lists to save space
    && rm -rf /var/lib/apt/lists/*

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
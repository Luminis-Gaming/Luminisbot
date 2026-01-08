# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# --- Install system dependencies ---
# Install basic system packages
RUN apt-get update && apt-get install -y \
    ca-certificates \
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

# --- Define the command to run your bot ---
# This will be run automatically when the container starts
CMD ["python", "my_discord_bot.py"]
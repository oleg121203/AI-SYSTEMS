# Use an appropriate base image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git dos2unix procps curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --upgrade pip

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements_async.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements_async.txt

# Copy the rest of your application code into the container
COPY . .

# Fix line endings, make sure script is executable, and configure git safe directory
RUN mkdir -p logs repo && \
    dos2unix /app/run_async_services.sh && \
    chmod +x /app/run_async_services.sh && \
    git config --global --add safe.directory /app/repo
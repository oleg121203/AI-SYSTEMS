# Use an appropriate base image
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git dos2unix procps curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --upgrade pip

# Create a non-root user and switch to it
RUN adduser -m $USER:$USER appuser && \
    mkdir -p /app && \
    chown $USER:$USER /app
USER $USER 

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY --chown=$USER:$USER requirements_async.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --user -r requirements_async.txt

# Copy the rest of your application code into the container
COPY --chown=$USER:$USER . .

# Fix line endings, make sure script is executable, and configure git safe directory
RUN mkdir -p logs repo && \
    dos2unix /app/run_async_services.sh && \
    chmod +x /app/run_async_services.sh && \
    git config --global --add safe.directory /app/repo
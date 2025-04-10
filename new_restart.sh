#!/bin/bash

# Stop and remove the existing container
docker-compose down ai-systems

# Remove the specific image for ai-systems (if it exists)
docker rmi ai-systems 2>/dev/null || true

# Set the working directory to match the Dockerfile
WORK_DIR=/app

# Remove contents of repo and logs directories created by the Dockerfile
rm -rf ${WORK_DIR}/repo/*
rm -rf ${WORK_DIR}/logs/*

# Remove Python cache files in the working directory
find ${WORK_DIR} -name '__pycache__' -type d -exec rm -rf {} +

# Remove the repo directory and recreate it
rm -rf ${WORK_DIR}/repo
mkdir ${WORK_DIR}/repo

# Ensure the repo directory has the correct ownership
chown -R $(id -u):$(id -g) ${WORK_DIR}/repo

# Start the Docker container
docker-compose up --build ai-systems

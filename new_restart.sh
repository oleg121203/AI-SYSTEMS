#!/bin/bash

# Stop and remove the existing container
docker-compose down

# Remove all untagged images
docker image prune -a -f

# Remove Python cache files
find . -name '__pycache__' -type d -exec rm -rf {} +

# Remove the repo directory
rm -rf repo

# Create the repo directory
mkdir repo

# Change the ownership of the repo directory to the current user
sudo chown -R $USER:$USER repo

# Initialize a new Git repository
git init

# Set global Git user email and name using environment variables if provided,
# otherwise use default values for automatic initialization on rebuild
if [ -z "$GIT_USER_EMAIL" ]; then
  git config --global user.email "oleg1203@gmail.com"
else
  git config --global user.email "$GIT_USER_EMAIL"
fi

if [ -z "$GIT_USER_NAME" ]; then
  git config --global user.name "Oleg Kizyma"
else
  git config --global user.name "$GIT_USER_NAME"
fi

# Add and commit initial files
git add .
git commit -m "Initial commit"

# Start the Docker container
docker-compose up --build
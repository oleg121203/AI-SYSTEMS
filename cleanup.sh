#!/bin/bash

# Remove all Docker containers
docker rm -f $(docker ps -aq)

# Remove all Docker images
docker rmi -f $(docker images -aq)

# Remove all Docker volumes
docker volume rm $(docker volume ls -q)

# Remove all Docker networks except pre-defined ones
docker network rm $(docker network ls -q | grep -vE '(bridge|host|none)')

# Remove contents of the logs directory
sudo rm -R -rf /home/dev/vscode/AI-SYSTEMS/logs/*

# Remove contents of the repo directory
sudo rm -R -rf /home/dev/vscode/AI-SYSTEMS/repo/*

# Remove contents of the additional directory
sudo rm -R -rf /home/dev/vscode/AI-SYSTEMS/vsc-ai-systems-13b85d4b2e5acd771ccf22063ff521d3fe2e6c5bb452335ba28ddbe68dd93592-features-uid/*

#!/bin/bash

# Check if the PID file exists
if [ -f "$HOME/.git_service.pid" ]; then
  PID=$(cat "$HOME/.git_service.pid")
  
  # Check if the process is still running
  if ps -p $PID > /dev/null; then
    echo "Stopping Git Service (PID $PID)..."
    kill $PID
    rm "$HOME/.git_service.pid"
    echo "Git Service stopped."
  else
    echo "Git Service is not running."
    rm "$HOME/.git_service.pid"
  fi
else
  echo "Git Service is not running."
fi

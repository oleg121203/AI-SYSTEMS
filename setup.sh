#!/bin/bash
set -e

echo "🚀 Starting setup for AI-SYSTEMS project..."

# Check if running in devcontainer or locally
if [ -n "$REMOTE_CONTAINERS" ] || [ -n "$CODESPACES" ] || [ -n "$VSCODE_REMOTE_CONTAINERS_SESSION" ]; then
    echo "📦 Running inside a development container"
    CONTAINER_MODE=true
else
    echo "💻 Running locally on host machine"
    CONTAINER_MODE=false
fi

# Update package list if in container
if [ "$CONTAINER_MODE" = true ]; then
    echo "🔄 Updating package lists..."
    sudo apt-get update -y
fi

# Python setup
echo "🐍 Setting up Python environment..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Install additional development tools if needed
echo "🛠️ Installing development tools..."
if [ -x "$(command -v npm)" ]; then
    echo "📦 Node.js is available"
    # Uncomment if you have package.json
    # if [ -f "package.json" ]; then
    #     npm install
    # fi
else
    echo "⚠️ Node.js not installed or not in PATH"
fi

# Set up Python pre-commit hooks (optional)
# if [ -x "$(command -v pre-commit)" ]; then
#     pre-commit install
# fi

# Set up permissions for scripts
echo "🔒 Setting execute permissions for scripts..."
for script in *.sh; do
    if [ -f "$script" ]; then
        chmod +x "$script"
        echo "  ✅ Made $script executable"
    fi
done

echo "✨ Setup complete! The AI-SYSTEMS project is ready to use."

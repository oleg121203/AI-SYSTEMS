#!/bin/bash

# Налаштування прав доступу
sudo chmod -R 755 "/home/dev/vscode/AI-SYSTEMS"
sudo chown -R $(id -u):$(id -g) "/home/dev/vscode/AI-SYSTEMS"

# Оновлення пакетів та встановлення shfmt і shellcheck
sudo apt-get update
sudo apt-get install -y shfmt shellcheck

# Оновлення pip і встановлення Python-пакетів
pip install --upgrade pip
pip install flake8==7.1.1 black==24.8.0 isort==5.13.2 pytest==8.3.3 httpx==0.27.2 pydantic==2.9.2

# Встановлення markdownlint-cli глобально
npm install -g markdownlint-cli

# Встановлення Node.js залежностей, якщо є package.json
if [ -f "/home/dev/vscode/AI-SYSTEMS/package.json" ]; then
    cd "/home/dev/vscode/AI-SYSTEMS" && npm install
fi

# Компіляція Rust проєкту, якщо є Cargo.toml
if [ -f "/home/dev/vscode/AI-SYSTEMS/Cargo.toml" ]; then
    cd "/home/dev/vscode/AI-SYSTEMS" && cargo build
fi

# Завантаження змінних з .env
set -a
. "/home/dev/vscode/AI-SYSTEMS/.env"

# Налаштування Git
git config --global user.name "$GIT_USER_NAME"
git config --global user.email "$GIT_USER_EMAIL"

# Перевірка SSH-з'єднання з GitHub
echo "Checking SSH connection..."
ssh -T git@github.com

# Ініціалізація Git-репозиторію для основного проєкту
cd "/home/dev/vscode/AI-SYSTEMS"
# Додавання основного каталогу до безпечних директорій Git
git config --global --add safe.directory "/home/dev/vscode/AI-SYSTEMS"
if [ ! -d .git ]; then
    git init
    git checkout -b "$MAIN_BRANCH"
    echo "$REPO_SUBFOLDER/" >.gitignore
    echo ".env" >>.gitignore
    git add .gitignore
    git commit -m "Initial commit with .gitignore"
    git remote add origin "git@github.com:oleg1203/AI-SYSTEMS.git"
    git push -u origin "$MAIN_BRANCH"
else
    git checkout "$MAIN_BRANCH" || git checkout -b "$MAIN_BRANCH"
fi

# Створення підпапки для ігрової програми
mkdir -p "/home/dev/vscode/AI-SYSTEMS/$REPO_SUBFOLDER/$GAME_PROGRAM_SUBFOLDER"
chmod -R 755 "/home/dev/vscode/AI-SYSTEMS"
chown -R $(id -u):$(id -g) "/home/dev/vscode/AI-SYSTEMS"

# Ініціалізація Git-репозиторію для ігрової програми
cd "/home/dev/vscode/AI-SYSTEMS/$REPO_SUBFOLDER/$GAME_PROGRAM_SUBFOLDER"
# Додавання підкаталогу гри до безпечних директорій Git
git config --global --add safe.directory "/home/dev/vscode/AI-SYSTEMS/$REPO_SUBFOLDER/$GAME_PROGRAM_SUBFOLDER"
if [ ! -d .git ]; then
    git init
    git checkout -b "$GAME_PROGRAM"
    echo 'Initial game files version control' >README.md
    git add README.md
    git commit -m "Initial commit for game files"
    git remote add origin "$GAME_PROGRAM_REPO_URL"
    git push -u origin "$GAME_PROGRAM"
fi

# Підтвердження завершення
echo "Setup completed successfully"

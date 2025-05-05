#!/bin/bash
# Скрипт для запуску тестів на різних типах файлів

set -e

# Кольори для виводу в термінал
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функція для виведення заголовка
print_header() {
    echo -e "\n${BLUE}=========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}=========================================${NC}\n"
}

# Перевірка потрібних інструментів
check_tools() {
    print_header "Перевірка наявності інструментів"

    # Перелік потрібних команд
    tools=("python3" "npm" "node" "eslint" "stylelint" "htmlhint" "pytest")

    for tool in "${tools[@]}"; do
        if command -v $tool &>/dev/null; then
            echo -e "${GREEN}✓ $tool знайдено${NC}"
        else
            echo -e "${RED}✗ $tool не знайдено. Будь ласка, встановіть його${NC}"
            if [ "$tool" == "python3" ]; then
                echo "   Команда: sudo apt-get install python3 python3-pip"
            elif [ "$tool" == "npm" ] || [ "$tool" == "node" ]; then
                echo "   Команда: curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt-get install -y nodejs"
            elif [ "$tool" == "eslint" ] || [ "$tool" == "stylelint" ] || [ "$tool" == "htmlhint" ]; then
                echo "   Команда: npm install -g $tool"
            elif [ "$tool" == "pytest" ]; then
                echo "   Команда: pip3 install pytest"
            fi
        fi
    done
}

# Встановлення необхідних пакетів
install_dependencies() {
    print_header "Встановлення залежностей"

    # Python залежності
    echo -e "${YELLOW}Встановлення Python залежностей...${NC}"
    pip3 install -r requirements.txt
    pip3 install pytest pytest-cov flake8 mypy black

    # Node.js залежності
    echo -e "${YELLOW}Встановлення Node.js залежностей...${NC}"
    if [ ! -f package.json ]; then
        echo '{
  "name": "web-tests",
  "version": "1.0.0",
  "description": "Web testing dependencies",
  "scripts": {
    "test": "jest"
  },
  "devDependencies": {
    "jest": "^29.5.0",
    "jest-environment-jsdom": "^29.5.0",
    "@testing-library/jest-dom": "^5.16.5",
    "@testing-library/react": "^14.0.0",
    "@testing-library/user-event": "^14.4.3",
    "eslint": "^8.38.0",
    "stylelint": "^15.4.0",
    "stylelint-config-standard": "^33.0.0",
    "stylelint-scss": "^4.6.0",
    "htmlhint": "^1.1.4",
    "sass-jest": "^0.1.7",
    "jest-transform-css": "^6.0.1",
    "puppeteer": "^19.8.5",
    "cypress": "^12.9.0",
    "playwright": "^1.32.3"
  }
}' >package.json
    fi

    npm install
}

# Запуск лінтерів для різних типів файлів
run_linters() {
    print_header "Запуск лінтерів"

    # Linting Python files
    echo -e "${YELLOW}Перевірка Python файлів...${NC}"
    python_files=$(find repo -name "*.py")
    if [ -n "$python_files" ]; then
        echo -e "${BLUE}Знайдені Python файли:${NC}"
        echo "$python_files"
        flake8 repo --count --select=E9,F63,F7,F82 --show-source --statistics || true
        black --check repo || true
        mypy repo || true
    else
        echo -e "${YELLOW}Python файли не знайдені${NC}"
    fi

    # Linting JavaScript files
    echo -e "\n${YELLOW}Перевірка JavaScript файлів...${NC}"
    js_files=$(find repo -name "*.js")
    if [ -n "$js_files" ]; then
        echo -e "${BLUE}Знайдені JavaScript файли:${NC}"
        echo "$js_files"
        echo '{"extends": ["eslint:recommended"], "parserOptions": {"ecmaVersion": 2020}, "env": {"browser": true, "node": true, "es6": true}}' >.eslintrc.json
        eslint "repo/**/*.js" --config .eslintrc.json || true
    else
        echo -e "${YELLOW}JavaScript файли не знайдені${NC}"
    fi

    # Linting HTML files
    echo -e "\n${YELLOW}Перевірка HTML файлів...${NC}"
    html_files=$(find repo -name "*.html")
    if [ -n "$html_files" ]; then
        echo -e "${BLUE}Знайдені HTML файли:${NC}"
        echo "$html_files"
        echo '{"tagname-lowercase": true, "attr-lowercase": true, "attr-value-double-quotes": true, "doctype-first": false, "tag-pair": true, "spec-char-escape": true, "id-unique": true, "src-not-empty": true, "attr-no-duplication": true, "title-require": true}' >.htmlhintrc
        htmlhint repo/**/*.html || true
    else
        echo -e "${YELLOW}HTML файли не знайдені${NC}"
    fi

    # Linting CSS files
    echo -e "\n${YELLOW}Перевірка CSS файлів...${NC}"
    css_files=$(find repo -name "*.css")
    if [ -n "$css_files" ]; then
        echo -e "${BLUE}Знайдені CSS файли:${NC}"
        echo "$css_files"
        echo '{"extends": "stylelint-config-standard"}' >.stylelintrc.json
        stylelint "repo/**/*.css" --config .stylelintrc.json --allow-empty-input || true
    else
        echo -e "${YELLOW}CSS файли не знайдені${NC}"
    fi

    # Linting SCSS files
    echo -e "\n${YELLOW}Перевірка SCSS файлів...${NC}"
    scss_files=$(find repo -name "*.scss")
    if [ -n "$scss_files" ]; then
        echo -e "${BLUE}Знайдені SCSS файли:${NC}"
        echo "$scss_files"
        echo '{"extends": "stylelint-config-standard", "plugins": ["stylelint-scss"]}' >.stylelintrc.json
        stylelint "repo/**/*.scss" --config .stylelintrc.json --allow-empty-input || true
    else
        echo -e "${YELLOW}SCSS файли не знайдені${NC}"
    fi
}

# Запуск тестів
run_tests() {
    print_header "Запуск тестів"

    # Python тести
    echo -e "${YELLOW}Запуск Python тестів...${NC}"
    python_tests=$(find repo/tests -name "*test*.py")
    if [ -n "$python_tests" ]; then
        echo -e "${BLUE}Знайдені тести Python:${NC}"
        echo "$python_tests"
        cd repo && python -m pytest tests/ -v || true
        cd ..
    else
        echo -e "${YELLOW}Python тести не знайдені${NC}"
    fi

    # JavaScript тести
    echo -e "\n${YELLOW}Запуск JavaScript тестів...${NC}"
    js_tests=$(find repo/tests -name "*test*.js")
    if [ -n "$js_tests" ]; then
        echo -e "${BLUE}Знайдені тести JavaScript:${NC}"
        echo "$js_tests"
        cd repo && npx jest tests/ || true
        cd ..
    else
        echo -e "${YELLOW}JavaScript тести не знайдені${NC}"
    fi

    # Тести React-компонентів
    echo -e "\n${YELLOW}Перевірка наявності тестів React-компонентів...${NC}"
    react_tests=$(find repo -name "*.test.jsx" -o -name "*.test.tsx")
    if [ -n "$react_tests" ]; then
        echo -e "${BLUE}Знайдені тести React-компонентів:${NC}"
        echo "$react_tests"
        cd repo && npx jest --testMatch='**/*.test.(jsx|tsx)' || true
        cd ..
    else
        echo -e "${YELLOW}Тести React-компонентів не знайдені${NC}"
    fi

    # Vue-тести
    echo -e "\n${YELLOW}Перевірка наявності тестів Vue-компонентів...${NC}"
    vue_tests=$(find repo -name "*.spec.js")
    if [ -n "$vue_tests" ]; then
        echo -e "${BLUE}Знайдені тести Vue-компонентів:${NC}"
        echo "$vue_tests"
        cd repo && npx jest --testMatch='**/*.spec.js' || true
        cd ..
    else
        echo -e "${YELLOW}Тести Vue-компонентів не знайдені${NC}"
    fi
}

# Генерація звіту з покриття тестами
generate_coverage_report() {
    print_header "Генерація звіту покриття тестами"

    # Python coverage
    echo -e "${YELLOW}Генерація звіту покриття Python-тестами...${NC}"
    if [ -d "repo/tests" ]; then
        cd repo && python -m pytest --cov=. tests/ --cov-report=html:coverage_report || true
        cd ..
        if [ -d "repo/coverage_report" ]; then
            echo -e "${GREEN}Звіт з покриття Python-тестами створено: repo/coverage_report/index.html${NC}"
        else
            echo -e "${RED}Не вдалося створити звіт з покриття Python-тестами${NC}"
        fi
    else
        echo -e "${YELLOW}Каталог з тестами Python не знайдено${NC}"
    fi

    # JavaScript coverage
    echo -e "\n${YELLOW}Генерація звіту покриття JavaScript-тестами...${NC}"
    js_tests=$(find repo/tests -name "*test*.js")
    if [ -n "$js_tests" ]; then
        cd repo && npx jest --coverage || true
        cd ..
        if [ -d "repo/coverage" ]; then
            echo -e "${GREEN}Звіт з покриття JavaScript-тестами створено: repo/coverage/lcov-report/index.html${NC}"
        else
            echo -e "${RED}Не вдалося створити звіт з покриття JavaScript-тестами${NC}"
        fi
    else
        echo -e "${YELLOW}JavaScript-тести не знайдено${NC}"
    fi
}

# Головна функція
main() {
    print_header "Запуск комплексного тестування"

    check_tools
    install_dependencies
    run_linters
    run_tests
    generate_coverage_report

    print_header "Тестування завершено"
    echo -e "${GREEN}✓ Усі перевірки завершено${NC}"
}

# Запуск головної функції
main

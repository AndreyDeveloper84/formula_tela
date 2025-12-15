# Руководство по безопасному использованию `git add` в Windows

## Проблема

При использовании `git add` с путями в Windows могут возникать ошибки, особенно когда:
- Пути содержат пробелы или специальные символы
- Файлы не существуют
- Используются неправильные относительные пути

## Правильный подход

### 1. Всегда проверяйте текущую директорию

```powershell
# Проверка текущей директории
cd c:\Users\user\PycharmProjects\mysite
pwd  # или Get-Location в PowerShell
```

### 2. Используйте `git status` для проверки изменений

```powershell
# Сначала проверьте, какие файлы изменены
git status --short
```

### 3. Безопасное добавление файлов

#### Вариант A: Добавление конкретных файлов с проверкой

```powershell
# Проверка существования файлов перед добавлением
$files = @(
    "mysite/services_app/yclients_api.py",
    "mysite/website/views.py",
    "mysite/website/templates/website/service_detail.html"
)

foreach ($file in $files) {
    if (Test-Path $file) {
        git add $file
        Write-Host "✅ Добавлен: $file"
    } else {
        Write-Host "⚠️ Файл не найден: $file"
    }
}
```

#### Вариант B: Использование git add с относительными путями

```powershell
# Убедитесь, что вы в корне репозитория
cd c:\Users\user\PycharmProjects\mysite

# Используйте относительные пути от корня репозитория
git add mysite/services_app/yclients_api.py
git add mysite/website/views.py
git add mysite/website/templates/website/service_detail.html
```

#### Вариант C: Добавление всех измененных файлов (осторожно!)

```powershell
# Добавить все измененные файлы
git add -u

# Или добавить все файлы (включая новые)
git add .
```

### 4. Проверка перед коммитом

```powershell
# Проверьте, что файлы добавлены
git status --short

# Проверьте, что файлы в staging area
git diff --cached --name-only
```

## Типичные ошибки и решения

### Ошибка: "fatal: pathspec 'file' did not match any files"

**Причина:** Файл не существует или путь неправильный

**Решение:**
```powershell
# Проверьте существование файла
Test-Path "mysite/services_app/yclients_api.py"

# Проверьте правильный путь
git ls-files mysite/services_app/yclients_api.py
```

### Ошибка: "fatal: 'path' is outside repository"

**Причина:** Использован абсолютный путь вместо относительного

**Решение:**
```powershell
# ❌ Неправильно
git add c:\Users\user\PycharmProjects\mysite\mysite\services_app\yclients_api.py

# ✅ Правильно
cd c:\Users\user\PycharmProjects\mysite
git add mysite/services_app/yclients_api.py
```

### Ошибка: Проблемы с кодировкой в путях

**Причина:** Имена файлов с кириллицей или специальными символами

**Решение:**
```powershell
# Используйте кавычки для путей с пробелами
git add "mysite/website/templates/website/service detail.html"

# Или экранируйте специальные символы
git add 'mysite/website/templates/website/service\ detail.html'
```

## Рекомендуемый workflow

```powershell
# 1. Перейдите в корень репозитория
cd c:\Users\user\PycharmProjects\mysite

# 2. Проверьте статус
git status --short

# 3. Добавьте файлы по одному или группой
git add mysite/services_app/yclients_api.py
git add mysite/website/views.py
git add mysite/website/templates/website/service_detail.html

# 4. Проверьте, что файлы добавлены
git status --short

# 5. Создайте коммит
git commit -m "fix: Описание изменений"

# 6. Отправьте в репозиторий
git push origin dev
```

## Альтернатива: Использование git add с паттернами

```powershell
# Добавить все файлы в директории
git add mysite/services_app/*.py

# Добавить все измененные Python файлы
git add mysite/**/*.py

# Добавить все файлы в директории (рекурсивно)
git add mysite/website/templates/
```

## Проверка структуры проекта

Перед добавлением файлов убедитесь, что понимаете структуру:

```
mysite/                          # Корень репозитория
├── mysite/                      # Django проект
│   ├── services_app/
│   │   └── yclients_api.py
│   ├── website/
│   │   ├── views.py
│   │   └── templates/
│   │       └── website/
│   │           └── service_detail.html
│   └── mysite/
│       ├── settings/
│       └── urls.py
```

## Автоматизация: Скрипт для безопасного git add

Создайте файл `safe-git-add.ps1`:

```powershell
param(
    [Parameter(Mandatory=$true)]
    [string[]]$Files
)

$repoRoot = "c:\Users\user\PycharmProjects\mysite"
Set-Location $repoRoot

$added = 0
$skipped = 0

foreach ($file in $Files) {
    if (Test-Path $file) {
        git add $file
        Write-Host "✅ Добавлен: $file" -ForegroundColor Green
        $added++
    } else {
        Write-Host "⚠️ Файл не найден: $file" -ForegroundColor Yellow
        $skipped++
    }
}

Write-Host "`nДобавлено: $added, Пропущено: $skipped"
git status --short
```

Использование:
```powershell
.\safe-git-add.ps1 -Files @(
    "mysite/services_app/yclients_api.py",
    "mysite/website/views.py"
)
```


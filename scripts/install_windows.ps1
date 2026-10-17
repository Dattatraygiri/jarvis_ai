$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configPath = Join-Path $root "resources\jarvis_config.json"
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$venv = Join-Path $root ".venv-jarvis"
$speechModel = Join-Path $root $config.speech_model_path
$speechModelName = Split-Path $speechModel -Leaf

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
$pythonCommand = $null
$pythonArguments = @()
if ($pythonLauncher) {
    $pythonCommand = $pythonLauncher.Source
    $pythonArguments = @("-3.12")
} else {
    $uvPythonRoot = Join-Path $env:APPDATA "uv\python"
    $uvPython = Get-ChildItem -Path $uvPythonRoot -Directory `
        -Filter "cpython-3.12.*-windows-x86_64-none" -ErrorAction SilentlyContinue `
        | Sort-Object Name -Descending | Select-Object -First 1
    if ($uvPython) {
        $candidate = Join-Path $uvPython.FullName "python.exe"
        if (Test-Path $candidate) { $pythonCommand = $candidate }
    }
}
if (-not $pythonCommand) {
    throw "Python 3.12 was not found. Install it with the 'py' launcher or uv, then rerun this script."
}
$pythonVersion = & $pythonCommand @pythonArguments -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
if ($LASTEXITCODE -ne 0 -or $pythonVersion -notmatch "^3\.12\.") {
    throw "Python 3.12 is required; found '$pythonVersion'."
}

if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
	& $pythonCommand @pythonArguments -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the project virtual environment." }
} else {
    $existingVersion = & (Join-Path $venv "Scripts\python.exe") -c "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    if ($LASTEXITCODE -ne 0 -or $existingVersion -notmatch "^3\.12\.") {
        throw "The existing .venv-jarvis uses Python '$existingVersion'. Move it aside before rerunning setup; it was left unchanged."
    }
}
& (Join-Path $venv "Scripts\python.exe") -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip." }
& (Join-Path $venv "Scripts\python.exe") -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install Jarvis Python dependencies." }

if (-not (Test-Path $speechModel)) {
    $downloadModel = Read-Host "Download the configured Vosk English speech model (about 130 MB)? [y/N]"
    if ($downloadModel -notmatch "^[Yy]$") {
        throw "Speech model is required. Rerun setup and approve its download."
    }
    $tempRoot = Join-Path $env:TEMP ("jarvis-setup-" + [guid]::NewGuid().ToString("N"))
    $archive = Join-Path $tempRoot "vosk-model.zip"
    $extract = Join-Path $tempRoot "extract"
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    try {
        Invoke-WebRequest `
            -Uri "https://alphacephei.com/vosk/models/$speechModelName.zip" `
            -OutFile $archive
        Expand-Archive -Path $archive -DestinationPath $extract -Force
        Move-Item (Join-Path $extract $speechModelName) $speechModel
    }
    finally {
        if (Test-Path $tempRoot) { Remove-Item $tempRoot -Recurse -Force }
    }
}

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    $ollamaPath = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $ollamaPath) {
        $ollama = [pscustomobject]@{ Source = $ollamaPath }
    }
}
if (-not $ollama) {
    throw "Ollama is required for private local AI. Install it from https://ollama.com/download, then rerun setup."
}
$models = & $ollama.Source list 2>$null | Out-String
if ($models -notmatch [regex]::Escape($config.model)) {
    $downloadModel = Read-Host "Download local AI model '$($config.model)'? This may require several GB. [y/N]"
    if ($downloadModel -notmatch "^[Yy]$") {
        throw "The configured Ollama model is required. Rerun setup and approve its download."
    }
    & $ollama.Source pull $config.model
    if ($LASTEXITCODE -ne 0) { throw "Ollama could not download the configured model." }
}

$registerStartup = Read-Host "Start Jarvis automatically when you sign in to Windows? [Y/n]"
if ($registerStartup -notmatch "^[Nn]$") {
    $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    $launcher = Join-Path $startup "JarvisAI.cmd"
    if (Test-Path $launcher) {
        throw "Startup launcher '$launcher' already exists. It was left unchanged."
    }
    $python = Join-Path $venv "Scripts\python.exe"
    $entryPoint = Join-Path $root "src\voice_assistant.py"
    $launcherContent = "@echo off`r`ncd /d `"$root`"`r`nstart `"`" /min `"$python`" `"$entryPoint`" start`r`n"
    Set-Content -Path $launcher -Value $launcherContent -Encoding Ascii
}

Write-Host "Jarvis setup is complete. Start it with: $venv\Scripts\python.exe $root\src\voice_assistant.py"

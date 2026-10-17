# Jarvis AI

Jarvis is a local Windows voice assistant. It listens for **"Hey Jarvis"**, uses
an Ollama model on this laptop to interpret requests, and dispatches only actions
implemented in the application. It does not run arbitrary model-generated shell
commands or write/delete files.

## Windows setup

1. Install Python 3.12 (64-bit), using either the `py` launcher or uv.
2. Install Ollama from [ollama.com/download](https://ollama.com/download).
3. In PowerShell, from this project folder, run:

	```powershell
	.\scripts\install_windows.ps1
	```

	The installer creates `.venv-jarvis`, installs Python dependencies, and asks before
	downloading the Vosk speech model, the configured Ollama model (several GB),
	and a per-user Windows sign-in launcher. It does not download models or add
	startup silently.
4. Start Jarvis manually with:

	```powershell
	.\.venv-jarvis\Scripts\python.exe .\src\voice_assistant.py
	```

Say **"Hey Jarvis"** followed by a request, or say **"Hey Jarvis"**, wait for
the listening prompt, then give the request. Say **"exit"** at any time to stop
Jarvis's microphone loop and cancel pending reminders. `Ctrl+C` also stops it.
After the wake phrase, Jarvis stays in conversation mode and accepts repeated
requests without another wake phrase until you say **"exit"** or use `stop`.

Control Jarvis from PowerShell in the project folder:

```powershell
.\.venv-jarvis\Scripts\python.exe .\src\voice_assistant.py start
.\.venv-jarvis\Scripts\python.exe .\src\voice_assistant.py status
.\.venv-jarvis\Scripts\python.exe .\src\voice_assistant.py stop
```

`start` opens Jarvis in a separate console and won't start a second copy.
`stop` signals Jarvis to close its microphone, reminder timers, and control
listener cleanly. These commands control the current session; the optional
Windows sign-in task controls automatic startup.

## Enabled actions

- Open Notepad, Calculator, or the default browser.
- Search the web in the browser.
- Read text, Markdown, Python, JSON, CSV, or log files inside this project only.
- Check Git status, diff summary, and recent commit history in this project.
- Set one-time reminders while Jarvis is running.
- Answer questions, tell the time/date, and calculate basic arithmetic.

Git access is read-only. File writes/deletes, arbitrary shell commands, and paths
outside this project are not available. The local model is not a substitute for
confirmation: review the action allow-list before adding new capabilities.

## Personal instructions and settings

Edit `resources/jarvis_config.json` to change the Ollama model, wake phrase, or
`instructions`. Instructions guide interpretation but cannot grant capabilities
that the application does not implement. The default model is `qwen2.5:3b`.

Reminders are in-memory and are canceled when Jarvis exits; they do not survive
shutdown or Windows sign-out. Exiting Jarvis stops its own audio and reminder
processing but does not close apps it opened or stop Ollama, which may serve
other local applications.

To remove the optional sign-in startup launcher, run:

```powershell
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\JarvisAI.cmd"
```

Run the safety checks with:

```powershell
.\.venv-jarvis\Scripts\python.exe -m unittest discover -s tests -v
```
"""Initialize a simple, extensible Jarvis task assistant."""

from __future__ import annotations

import ast
import json
import operator
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen


class JarvisAI:
	"""Handle text requests and dispatch them to registered task handlers."""

	def __init__(
		self,
		name: str = "Jarvis",
		workspace: Path | None = None,
		model: str = "qwen2.5:3b",
		ollama_url: str = "http://127.0.0.1:11434/api/chat",
		instructions: str = "",
		notify: Callable[[str], None] | None = None,
	) -> None:
		self.name = name
		self.workspace = (workspace or Path(__file__).resolve().parent.parent).resolve()
		self.model = model
		self.ollama_url = ollama_url
		self.instructions = instructions
		self.notify = notify
		self._reminders: set[threading.Timer] = set()
		self._reminder_lock = threading.Lock()
		self.tasks: dict[str, tuple[str, Callable[[str], str]]] = {}
		self.register_task("time", "Tell the current time", self._time)
		self.register_task("date", "Tell today's date", self._date)
		self.register_task("calculate", "Calculate basic arithmetic", self._calculate)
		self.register_task("git", "Explain a safe Git workflow", self._git_workflow)
		self.register_task("help", "List available tasks", self._help)

	def register_task(self, name: str, description: str, handler: Callable[[str], str]) -> None:
		"""Register a new task, such as a weather lookup supplied by your app."""
		self.tasks[name.lower()] = (description, handler)

	def ask(self, request: str) -> str:
		"""Respond to requests like 'Hey Jarvis, what time is it?' or 'calculate 2 + 2'."""
		text = request.strip()
		if not text:
			return "What would you like me to do?"

		lowered = text.lower()
		for wake_word in ("hey jarvis", "jarvis"):
			if lowered.startswith(wake_word):
				text = text[len(wake_word):].lstrip(" ,.!?")
				break
		lowered = text.lower()
		if not lowered:
			return "I'm listening. What would you like me to do?"

		if any(phrase in lowered for phrase in ("what time", "current time", "tell me the time")):
			return self._time("")
		if any(phrase in lowered for phrase in ("what date", "today's date", "what day is it")):
			return self._date("")
		if lowered in {"help", "what can you do", "list tasks"}:
			return self._help("")

		for prefix in ("calculate ", "compute "):
			if lowered.startswith(prefix):
				return self._calculate(text[len(prefix):].rstrip("?"))

		task_name, _, argument = text.partition(" ")
		task = self.tasks.get(task_name.lower())
		if task:
			return task[1](argument.strip())
		try:
			return self._dispatch(self._interpret(text))
		except (URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
			return f"I couldn't process that request: {error}"

	def _interpret(self, request: str) -> dict[str, object]:
		"""Ask the local Ollama model for a constrained action, never executable code."""
		allowed_actions = (
			"answer, open_app, web_search, read_file, git, schedule_reminder, "
			"time, date, calculate"
		)
		system_prompt = (
			"You are Jarvis, a laptop assistant. Follow these user instructions, but "
			"never expand your permissions: " + (self.instructions or "No extra instructions.") + "\n"
			f"Return only a JSON object with action and arguments. Allowed actions: {allowed_actions}. "
			"For git, arguments.operation must be status, diff, or log. For open_app, "
			"arguments.name must be notepad, calculator, or browser. For read_file, "
			"arguments.path must be relative to the project. For schedule_reminder, "
			"arguments.when must be an ISO local date/time and arguments.message the reminder. "
			"Never request or invent shell commands, file writes/deletes, or paths outside the project. "
			"Use action answer for ordinary questions and put its response in arguments.text."
		)
		payload = json.dumps({
			"model": self.model,
			"stream": False,
			"format": "json",
			"messages": [
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": request},
			],
			"options": {"temperature": 0},
		}).encode("utf-8")
		request_data = Request(
			self.ollama_url,
			data=payload,
			headers={"Content-Type": "application/json"},
			method="POST",
		)
		with urlopen(request_data, timeout=45) as response:
			result = json.loads(response.read().decode("utf-8"))
		return json.loads(result["message"]["content"])

	def _dispatch(self, intent: dict[str, object]) -> str:
		"""Dispatch only validated actions implemented by this application."""
		action = intent.get("action")
		arguments = intent.get("arguments", {})
		if not isinstance(arguments, dict):
			return "I couldn't understand the request arguments."
		if action == "answer":
			return self._argument(arguments, "text") or "I don't have an answer for that."
		if action == "time":
			return self._time("")
		if action == "date":
			return self._date("")
		if action == "calculate":
			return self._calculate(self._argument(arguments, "expression"))
		if action == "open_app":
			return self._open_app(self._argument(arguments, "name"))
		if action == "web_search":
			query = self._argument(arguments, "query")
			if not query:
				return "Tell me what you'd like to search for."
			webbrowser.open("https://www.google.com/search?q=" + quote_plus(query))
			return f"I opened a web search for {query}."
		if action == "read_file":
			return self._read_file(self._argument(arguments, "path"))
		if action == "git":
			return self._run_git(self._argument(arguments, "operation"))
		if action == "schedule_reminder":
			return self._schedule_reminder(
				self._argument(arguments, "when"),
				self._argument(arguments, "message"),
			)
		return "That action isn't enabled."

	@staticmethod
	def _argument(arguments: dict[str, object], name: str) -> str:
		value = arguments.get(name, "")
		return value.strip() if isinstance(value, str) else ""

	@staticmethod
	def _open_app(name: str) -> str:
		apps = {"notepad": "notepad.exe", "calculator": "calc.exe"}
		if name == "browser":
			webbrowser.open("https://www.google.com")
			return "I opened your browser."
		app = apps.get(name.lower())
		if not app:
			return "I can open only Notepad, Calculator, or your browser."
		try:
			subprocess.Popen([app], shell=False)
		except OSError as error:
			return f"I couldn't open {name}: {error}"
		return f"I opened {name}."

	def _read_file(self, relative_path: str) -> str:
		if not relative_path:
			return "Tell me the project-relative file path to read."
		path = (self.workspace / relative_path).resolve()
		try:
			path.relative_to(self.workspace)
		except ValueError:
			return "I can read files only inside this project."
		if path.suffix.lower() not in {".txt", ".md", ".py", ".json", ".csv", ".log"}:
			return "That file type isn't allowed for reading."
		try:
			if path.stat().st_size > 256_000:
				return "That file is too large to read (limit: 256 KB)."
			return path.read_text(encoding="utf-8")
		except (OSError, UnicodeError) as error:
			return f"I couldn't read that file: {error}"

	def _run_git(self, operation: str) -> str:
		commands = {
			"status": ["git", "status", "--short", "--branch"],
			"diff": ["git", "diff", "--stat"],
			"log": ["git", "log", "-5", "--oneline"],
		}
		command = commands.get(operation)
		if not command:
			return "Allowed Git checks are status, diff, and log."
		try:
			result = subprocess.run(
				command, cwd=self.workspace, capture_output=True, text=True,
				check=False, timeout=10, shell=False,
			)
		except (OSError, subprocess.TimeoutExpired) as error:
			return f"I couldn't run that Git check: {error}"
		output = result.stdout.strip() or result.stderr.strip()
		return output or "Git check completed; there is no output."

	def _schedule_reminder(self, when: str, message: str) -> str:
		if not when or not message:
			return "Give me a reminder time and message."
		try:
			reminder_time = datetime.fromisoformat(when)
		except ValueError:
			return "I couldn't read that time. Please say a date and time."
		delay = (reminder_time - datetime.now()).total_seconds()
		if delay <= 0:
			return "That reminder time has already passed."
		timer = threading.Timer(delay, self._deliver_reminder, args=(message,))
		timer.daemon = True
		with self._reminder_lock:
			self._reminders.add(timer)
		timer.start()
		return f"Reminder set for {reminder_time.strftime('%Y-%m-%d %I:%M %p')}."

	def _deliver_reminder(self, message: str) -> None:
		reminder = f"Reminder: {message}"
		if self.notify is not None:
			self.notify(reminder)
		else:
			print(f"\nJarvis {reminder}")

	def close(self) -> None:
		"""Cancel pending reminder timers when the assistant exits."""
		with self._reminder_lock:
			for timer in self._reminders:
				timer.cancel()
			self._reminders.clear()

	def _help(self, _argument: str) -> str:
		available = "; ".join(
			f"{name}: {description}" for name, (description, _) in self.tasks.items()
		)
		return f"Available tasks: {available}. Add tasks with register_task()."

	@staticmethod
	def _time(_argument: str) -> str:
		return f"It is {datetime.now().strftime('%I:%M %p')}."

	@staticmethod
	def _date(_argument: str) -> str:
		return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}."

	@staticmethod
	def _git_workflow(_argument: str) -> str:
		return (
			"Git workflow: run 'git status' to review changes, then 'git add <files>' "
			"to stage them. Review with 'git diff --staged', commit with "
			"'git commit -m \"message\"', then use 'git pull --rebase' before "
			"'git push'. These commands are guidance only; Jarvis will not run them."
		)

	@staticmethod
	def _calculate(expression: str) -> str:
		"""Evaluate arithmetic expressions only; arbitrary Python is not executed."""
		allowed = {
			ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
			ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
			ast.Mod: operator.mod, ast.Pow: operator.pow,
			ast.UAdd: operator.pos, ast.USub: operator.neg,
		}

		def evaluate(node: ast.AST) -> int | float:
			if isinstance(node, ast.Expression):
				return evaluate(node.body)
			if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
				return node.value
			if isinstance(node, ast.BinOp) and type(node.op) in allowed:
				return allowed[type(node.op)](evaluate(node.left), evaluate(node.right))
			if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
				return allowed[type(node.op)](evaluate(node.operand))
			raise ValueError("Use numbers and basic arithmetic operators only.")

		try:
			return f"The answer is {evaluate(ast.parse(expression, mode='eval'))}."
		except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as error:
			return f"I couldn't calculate that: {error}"


def initialize_jarvis() -> JarvisAI:
	"""Create a ready-to-use Jarvis assistant."""
	return JarvisAI()


if __name__ == "__main__":
	jarvis = initialize_jarvis()
	print("Jarvis is ready. Type 'exit' or 'destroy' to quit.")
	try:
		while True:
			try:
				request = input("You: ").strip()
			except (EOFError, KeyboardInterrupt):
				print("\nGoodbye!")
				break
			if request.lower() in {"exit", "quit", "destroy", "shutdown"}:
				print("Goodbye!")
				break
			print(f"Jarvis: {jarvis.ask(request)}")
	finally:
		jarvis.close()

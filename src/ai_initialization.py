"""Initialize a simple, extensible Jarvis task assistant."""

from __future__ import annotations

import ast
import operator
from datetime import datetime
from typing import Callable


class JarvisAI:
	"""Handle text requests and dispatch them to registered task handlers."""

	def __init__(self, name: str = "Jarvis") -> None:
		self.name = name
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

		if any(phrase in lowered for phrase in ("what time", "current time", "tell me the time")):
			return self._time("")
		if any(phrase in lowered for phrase in ("what date", "today's date", "what day is it")):
			return self._date("")
		if lowered in {"help", "what can you do", "list tasks"}:
			return self._help("")

		for prefix in ("calculate ", "compute ", "what is "):
			if lowered.startswith(prefix):
				return self._calculate(text[len(prefix):].rstrip("?"))

		task_name, _, argument = text.partition(" ")
		task = self.tasks.get(task_name.lower())
		if task:
			return task[1](argument.strip())
		return f"I don't know that task yet. {self._help('')}"

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

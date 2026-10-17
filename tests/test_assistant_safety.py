import socket
import queue
import threading
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.ai_initialization import JarvisAI
from src.voice_assistant import (
	_serve_control_requests,
	_discard_queued_audio,
	build_wake_grammar,
	extract_wake_command,
	is_exit_phrase,
	send_control_command,
)


class AssistantSafetyTests(unittest.TestCase):
	def setUp(self) -> None:
		self.assistant = JarvisAI(workspace=Path(__file__).resolve().parents[1])

	def tearDown(self) -> None:
		self.assistant.close()

	def test_arithmetic_remains_available_without_local_model(self) -> None:
		self.assertEqual(self.assistant.ask("Hey Jarvis, calculate 2 + 2"), "The answer is 4.")

	def test_general_what_is_question_reaches_local_model(self) -> None:
		with patch.object(
			self.assistant,
			"_interpret",
			return_value={
				"action": "answer",
				"arguments": {"text": "Photosynthesis converts light into chemical energy."},
			},
		) as interpret:
			self.assertIn("chemical energy", self.assistant.ask("What is photosynthesis?"))
		interpret.assert_called_once_with("What is photosynthesis?")

	def test_project_file_can_be_read(self) -> None:
		self.assertIn("local Windows voice assistant", self.assistant._read_file("README.md"))

	def test_file_access_cannot_escape_project(self) -> None:
		self.assertIn("only inside this project", self.assistant._read_file("../README.md"))

	def test_git_allows_only_read_only_commands_inside_project(self) -> None:
		with patch(
			"src.ai_initialization.subprocess.run",
			return_value=SimpleNamespace(stdout="## main", stderr="", returncode=0),
		) as run:
			self.assertEqual(self.assistant._run_git("status"), "## main")
		run.assert_called_once_with(
			["git", "status", "--short", "--branch"],
			cwd=self.assistant.workspace,
			capture_output=True,
			text=True,
			check=False,
			timeout=10,
			shell=False,
		)

	def test_git_rejects_mutating_operations(self) -> None:
		with patch("src.ai_initialization.subprocess.run") as run:
			self.assertIn("Allowed Git checks", self.assistant._run_git("push"))
		run.assert_not_called()

	def test_model_cannot_dispatch_unimplemented_shell_action(self) -> None:
		self.assertEqual(
			self.assistant._dispatch({"action": "run_shell", "arguments": {"command": "del *"}}),
			"That action isn't enabled.",
		)

	def test_only_approved_apps_can_be_opened(self) -> None:
		self.assertIn("only Notepad", self.assistant._open_app("powershell"))

	def test_close_cancels_pending_reminders(self) -> None:
		when = (datetime.now() + timedelta(hours=1)).isoformat()
		self.assistant._schedule_reminder(when, "test reminder")
		timer = next(iter(self.assistant._reminders))
		self.assistant.close()
		self.assertTrue(timer.finished.is_set())

	def test_exit_phrase_is_standalone(self) -> None:
		self.assertTrue(is_exit_phrase("EXIT!"))
		self.assertFalse(is_exit_phrase("hey jarvis exit"))
		self.assertFalse(is_exit_phrase("exciting"))

	def test_wake_phrase_is_configurable(self) -> None:
		self.assertEqual(extract_wake_command("Hey Jarvis, open Notepad", "hey jarvis"), "open Notepad")
		self.assertEqual(extract_wake_command("Computer, open browser", "computer"), "open browser")
		self.assertIsNone(extract_wake_command("Jarvis open browser", "computer"))

	def test_wake_grammar_does_not_include_shutdown_commands(self) -> None:
		self.assertEqual(build_wake_grammar("Hey Jarvis"), json.dumps(["hey jarvis", "[unk]"]))

	def test_speech_audio_is_discarded_before_listening_resumes(self) -> None:
		buffered = queue.Queue()
		buffered.put(b"assistant echo")
		_discard_queued_audio(buffered)
		self.assertTrue(buffered.empty())

	def test_local_control_can_report_status_and_stop(self) -> None:
		listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		listener.bind(("127.0.0.1", 0))
		listener.listen(4)
		listener.settimeout(0.05)
		port = listener.getsockname()[1]
		stopping = threading.Event()
		worker = threading.Thread(
			target=_serve_control_requests,
			args=(listener, stopping),
			daemon=True,
		)
		worker.start()
		try:
			self.assertEqual(send_control_command(port, "status"), "running")
			self.assertEqual(send_control_command(port, "stop"), "stopping")
			self.assertTrue(stopping.wait(1))
		finally:
			listener.close()
			worker.join(timeout=1)
		self.assertFalse(worker.is_alive())


if __name__ == "__main__":
	unittest.main()

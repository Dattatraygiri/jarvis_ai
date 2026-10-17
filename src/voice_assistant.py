"""Run Jarvis as a local, wake-word voice assistant on Windows."""

from __future__ import annotations

import importlib
import argparse
import json
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
	from .ai_initialization import JarvisAI
except ImportError:
	from ai_initialization import JarvisAI


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "resources" / "jarvis_config.json"


def load_config() -> dict[str, Any]:
	with CONFIG_PATH.open(encoding="utf-8") as config_file:
		return json.load(config_file)


def is_exit_phrase(transcript: str) -> bool:
	return transcript.lower().strip(" .,!?") in {"exit", "quit", "shutdown"}


def extract_wake_command(transcript: str, wake_phrase: str) -> str | None:
	words = wake_phrase.strip().split()
	if not words:
		return None
	pattern = r"\b" + r"\s+".join(re.escape(word) for word in words) + r"\b"
	match = re.search(pattern, transcript, re.IGNORECASE)
	if match is None:
		return None
	return transcript[match.end():].strip(" ,.!?")


def build_wake_grammar(wake_phrase: str) -> str:
	return json.dumps([wake_phrase.lower(), "[unk]"])


def build_wake_grammar(wake_phrase: str) -> str:
	return json.dumps([wake_phrase.lower(), "[unk]"])


def _discard_queued_audio(audio_queue: queue.Queue[bytes]) -> None:
	while True:
		try:
			audio_queue.get_nowait()
		except queue.Empty:
			return


def send_control_command(port: int, command: str) -> str:
	with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
		connection.sendall((command + "\n").encode("ascii"))
		return connection.recv(64).decode("ascii").strip()


def _serve_control_requests(listener: socket.socket, stopping: threading.Event) -> None:
	while not stopping.is_set():
		try:
			connection, _ = listener.accept()
		except socket.timeout:
			continue
		except OSError:
			return
		with connection:
			connection.settimeout(1.0)
			try:
				command = connection.recv(64).decode("ascii").strip().lower()
			except (OSError, UnicodeError):
				command = ""
			if command == "status":
				response = "running"
			elif command == "stop":
				stopping.set()
				response = "stopping"
			else:
				response = "unsupported"
			try:
				connection.sendall((response + "\n").encode("ascii"))
			except OSError:
				pass


def control(action: str) -> int:
	try:
		config = load_config()
		port = config.get("control_port", 47831)
		if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
			raise ValueError("control_port must be an integer from 1024 to 65535")
	except (OSError, json.JSONDecodeError, ValueError) as error:
		print(f"Jarvis control is unavailable: {error}", file=sys.stderr)
		return 1

	if action == "start":
		try:
			if send_control_command(port, "status") == "running":
				print("Jarvis is already running.")
				return 0
		except OSError:
			pass
		process = subprocess.Popen(
			[sys.executable, str(Path(__file__).resolve()), "run"],
			cwd=ROOT,
			shell=False,
			creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
		)
		print(f"Jarvis is starting (PID {process.pid}).")
		return 0

	try:
		response = send_control_command(port, action)
	except OSError:
		response = "not running"
	print(f"Jarvis status: {response}.")
	return 0 if response in {"running", "stopping", "not running"} else 1


def run() -> int:
	try:
		config = load_config()
		vosk = importlib.import_module("vosk")
		sounddevice = importlib.import_module("sounddevice")
		pyttsx3 = importlib.import_module("pyttsx3")
	except (ImportError, OSError, json.JSONDecodeError) as error:
		print(f"Jarvis setup is incomplete: {error}", file=sys.stderr)
		return 1

	model_path = ROOT / config["speech_model_path"]
	if not model_path.is_dir():
		print(
			f"Speech model not found at {model_path}. Run scripts/install_windows.ps1 first.",
			file=sys.stderr,
		)
		return 1

	try:
		speech_model = vosk.Model(str(model_path))
		wake_phrase = config.get("wake_phrase", "hey jarvis")
		wake_recognizer = vosk.KaldiRecognizer(
			speech_model, 16000, build_wake_grammar(wake_phrase)
		)
		recognizer = vosk.KaldiRecognizer(speech_model, 16000)
		speaker = pyttsx3.init()
	except Exception as error:
		print(f"Jarvis could not initialize audio: {error}", file=sys.stderr)
		return 1

	audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=32)
	command_queue: queue.Queue[str | None] = queue.Queue(maxsize=8)
	message_queue: queue.Queue[str] = queue.Queue()
	stopping = threading.Event()
	speaking = threading.Event()
	control_port = config.get("control_port", 47831)
	if isinstance(control_port, bool) or not isinstance(control_port, int) or not 1024 <= control_port <= 65535:
		print("Jarvis control_port must be an integer from 1024 to 65535.", file=sys.stderr)
		speaker.stop()
		return 1
	control_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	control_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	try:
		control_listener.bind(("127.0.0.1", control_port))
		control_listener.listen(4)
		control_listener.settimeout(0.5)
	except OSError as error:
		control_listener.close()
		speaker.stop()
		print(f"Jarvis control port {control_port} is unavailable: {error}", file=sys.stderr)
		return 1
	control_worker = threading.Thread(
		target=_serve_control_requests,
		args=(control_listener, stopping),
		name="jarvis-control",
		daemon=True,
	)
	control_worker.start()

	def audio_callback(indata: bytes, _frames: int, _time_info: object, status: object) -> None:
		if speaking.is_set():
			return
		if status:
			message_queue.put(f"Microphone status: {status}")
		try:
			audio_queue.put_nowait(bytes(indata))
		except queue.Full:
			pass

	def deliver_reminder(message: str) -> None:
		message_queue.put(message)

	assistant = JarvisAI(
		model=config["model"],
		ollama_url=config["ollama_url"],
		instructions=config.get("instructions", ""),
		notify=deliver_reminder,
	)

	def process_commands() -> None:
		while not stopping.is_set():
			try:
				command = command_queue.get(timeout=0.2)
			except queue.Empty:
				continue
			if command is None:
				return
			message_queue.put(assistant.ask(command))

	worker = threading.Thread(target=process_commands, name="jarvis-command", daemon=True)
	worker.start()

	def speak(message: str) -> None:
		print(f"Jarvis: {message}", flush=True)
		speaking.set()
		_discard_queued_audio(audio_queue)
		try:
			speaker.say(message)
			speaker.runAndWait()
		finally:
			_discard_queued_audio(audio_queue)
			recognizer.Reset()
			wake_recognizer.Reset()
			speaking.clear()

	session_active = False
	wake_only_pending = False
	last_partial = ""
	print(f"Jarvis is listening for '{wake_phrase}'. Say 'exit' or run the stop command.")
	try:
		with sounddevice.RawInputStream(
			samplerate=16000,
			blocksize=8000,
			dtype="int16",
			channels=1,
			callback=audio_callback,
		):
			while not stopping.is_set():
				try:
					message = message_queue.get_nowait()
				except queue.Empty:
					message = ""
				if message:
					speak(message)

				try:
					audio = audio_queue.get(timeout=0.1)
				except queue.Empty:
					continue
				if not session_active and wake_recognizer.AcceptWaveform(audio):
					wake_transcript = json.loads(wake_recognizer.Result()).get("text", "").strip()
					wake_command = extract_wake_command(wake_transcript, wake_phrase)
					if wake_command is not None:
						session_active = True
						wake_only_pending = not wake_command
						print("Wake phrase detected.", flush=True)
				if not recognizer.AcceptWaveform(audio):
					partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()
					if partial and partial != last_partial:
						print(f"You (partial): {partial}", flush=True)
					last_partial = partial
					continue
				last_partial = ""
				transcript = json.loads(recognizer.Result()).get("text", "").strip()
				if not transcript:
					continue
				print(f"You: {transcript}", flush=True)
				if is_exit_phrase(transcript):
					stopping.set()
					break

				command = extract_wake_command(transcript, wake_phrase)
				if wake_only_pending and command is None and len(transcript.split()) <= 2:
					wake_only_pending = False
					session_active = True
					speak("I'm listening.")
					continue
				wake_only_pending = False
				if command is not None:
					if not command:
						session_active = True
						speak("I'm listening.")
						continue
					if is_exit_phrase(command):
						stopping.set()
						break
				elif not session_active:
					continue
				else:
					command = transcript

				if command_queue.full():
					speak("My request queue is full. Please wait.")
					continue
				command_queue.put_nowait(command)
	except KeyboardInterrupt:
		stopping.set()
	except Exception as error:
		print(f"Voice assistant stopped: {error}", file=sys.stderr)
		return 1
	finally:
		stopping.set()
		control_listener.close()
		control_worker.join(timeout=1)
		try:
			command_queue.put_nowait(None)
		except queue.Full:
			pass
		assistant.close()
		speaker.stop()
	print("Goodbye!")
	return 0


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Run or control the Jarvis voice assistant.")
	parser.add_argument("action", nargs="?", choices=("run", "start", "stop", "status"), default="run")
	arguments = parser.parse_args()
	raise SystemExit(run() if arguments.action == "run" else control(arguments.action))

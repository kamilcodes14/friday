"""
F.R.I.D.A.Y. - Female Replacement Intelligent Digital Assistant Youth
Core assistant logic (voice, wake detection, speech recognition, Claude brain,
interview-practice coach). No UI code lives here — friday_gui.py wraps this
with a Tkinter HUD, and this module also still runs standalone (console mode)
if you just run `python friday_core.py`.

Author: Syed | Powered by Claude AI
"""

import os
import sys
import time
import json
import datetime
import threading
import subprocess
import audioop

import pyaudio
import pyttsx3
import speech_recognition as sr
import anthropic

# ─────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "your-api-key-here")
BRAIN_MODEL = "claude-sonnet-4-20250514"

CLAP_THRESHOLD      = 3000   # Adjust based on your mic sensitivity (higher = louder clap needed)
DOUBLE_CLAP_WINDOW  = 1.2    # seconds between two claps to count as "double clap"
LISTEN_TIMEOUT      = 8      # seconds to wait for speech input
SAMPLE_RATE         = 44100
CHUNK               = 1024

INTERVIEW_TRIGGERS = ["mock interview", "practice interview", "interview practice", "start interview"]
INTERVIEW_STOP     = ["stop interview", "end interview", "cancel interview"]

FRIDAY_SYSTEM_PROMPT = """You are F.R.I.D.A.Y. (Female Replacement Intelligent Digital Assistant Youth),
the AI assistant of Syed. You are modeled after the AI from Iron Man.
Your personality: calm, professional, slightly witty, highly capable, loyal to Syed.
Always address the user as "Syed" or "Boss" (alternate naturally).
Keep responses concise and conversational — you are a voice assistant, not an essay writer.
You help with tasks, answer questions, give reminders, and manage the computer when asked.
Current user: Syed — CS student at UMT Lahore, interested in AI, space, and tech."""


# ─────────────────────────────────────────
#  VOICE ENGINE
# ─────────────────────────────────────────
class VoiceEngine:
    def __init__(self, on_speak=None):
        """on_speak(text) fires right before speech is spoken — a GUI can hook this to log/animate."""
        self.engine = pyttsx3.init()
        self._configure_voice()
        self.on_speak = on_speak or (lambda text: None)

    def _configure_voice(self):
        voices = self.engine.getProperty('voices')
        female_voice = None
        for voice in voices:
            if any(k in voice.name.lower() for k in ['female', 'zira', 'hazel', 'susan', 'helena', 'karen', 'samantha']):
                female_voice = voice.id
                break
        if female_voice:
            self.engine.setProperty('voice', female_voice)
        elif len(voices) > 1:
            self.engine.setProperty('voice', voices[1].id)

        self.engine.setProperty('rate', 175)
        self.engine.setProperty('volume', 0.95)

    def speak(self, text: str):
        print(f"\n[F.R.I.D.A.Y.] {text}")
        self.on_speak(text)
        self.engine.say(text)
        self.engine.runAndWait()


# ─────────────────────────────────────────
#  CLAP DETECTOR  (double clap OR a manual trigger from a GUI button)
# ─────────────────────────────────────────
class ClapDetector:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.running = False
        self.manual_trigger = threading.Event()  # set() this from a GUI thread to force a wake

    def _open_stream(self):
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

    def _close_stream(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

    def listen_for_double_clap(self, callback):
        """Blocks. Calls callback() on a double clap OR when manual_trigger is set."""
        self._open_stream()
        self.running = True
        print("[F.R.I.D.A.Y.] Listening for double clap to wake up...")

        clap_times = []
        in_clap = False

        try:
            while self.running:
                if self.manual_trigger.is_set():
                    self.manual_trigger.clear()
                    clap_times = []
                    self._close_stream()
                    callback()
                    time.sleep(0.5)
                    if self.running:
                        self._open_stream()
                    continue

                data = self.stream.read(CHUNK, exception_on_overflow=False)
                rms = audioop.rms(data, 2)
                now = time.time()

                if rms > CLAP_THRESHOLD and not in_clap:
                    in_clap = True
                    clap_times.append(now)
                    clap_times = [t for t in clap_times if now - t < DOUBLE_CLAP_WINDOW]

                    if len(clap_times) >= 2:
                        gap = clap_times[-1] - clap_times[-2]
                        if 0.1 < gap < DOUBLE_CLAP_WINDOW:
                            clap_times = []
                            self._close_stream()
                            callback()
                            time.sleep(2)
                            if self.running:
                                self._open_stream()

                elif rms <= CLAP_THRESHOLD // 2:
                    in_clap = False

        except KeyboardInterrupt:
            pass
        finally:
            self._close_stream()

    def stop(self):
        self.running = False
        self.manual_trigger.set()  # unstick a blocking stream.read() ASAP


# ─────────────────────────────────────────
#  SPEECH RECOGNIZER
# ─────────────────────────────────────────
class SpeechListener:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True

    def listen(self):
        with sr.Microphone() as source:
            print("[F.R.I.D.A.Y.] Listening for your command...")
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recognizer.listen(source, timeout=LISTEN_TIMEOUT, phrase_time_limit=15)
                text = self.recognizer.recognize_google(audio)
                print(f"[YOU] {text}")
                return text.lower()
            except sr.WaitTimeoutError:
                return None
            except sr.UnknownValueError:
                return None
            except sr.RequestError as e:
                print(f"[ERROR] Speech recognition failed: {e}")
                return None


# ─────────────────────────────────────────
#  CLAUDE AI BRAIN
# ─────────────────────────────────────────
class FridayBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.conversation_history = []

    def think(self, user_input: str) -> str:
        self.conversation_history.append({"role": "user", "content": user_input})
        history = self.conversation_history[-20:]

        try:
            response = self.client.messages.create(
                model=BRAIN_MODEL,
                max_tokens=300,
                system=FRIDAY_SYSTEM_PROMPT,
                messages=history
            )
            reply = response.content[0].text
            self.conversation_history.append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            return f"I'm having trouble connecting to my neural network, Boss. Error: {str(e)}"

    def reset_memory(self):
        self.conversation_history = []


# ─────────────────────────────────────────
#  INTERVIEW COACH  (new feature)
# ─────────────────────────────────────────
class InterviewCoach:
    """Runs a short mock-interview: generates role-specific questions with Claude,
    asks them one at a time, and produces closing feedback once all are answered."""

    def __init__(self, client: anthropic.Anthropic, model: str = BRAIN_MODEL, num_questions: int = 5):
        self.client = client
        self.model = model
        self.num_questions = num_questions
        self.role = None
        self.questions = []
        self.transcript = []       # [{"question":..., "answer":...}, ...]
        self.current_index = 0
        self.active = False

    def start(self, role: str) -> str:
        """Generates questions for `role` and returns the first question."""
        self.role = role.strip()
        self.transcript = []
        self.current_index = 0
        self.questions = self._generate_questions(self.role)
        self.active = True
        return self.questions[0]

    def submit_answer(self, answer: str):
        """Records the answer to the current question.
        Returns (next_text, done) — next_text is either the next question,
        or the final feedback summary once done=True."""
        question = self.questions[self.current_index]
        self.transcript.append({"question": question, "answer": answer})
        self.current_index += 1

        if self.current_index < len(self.questions):
            return self.questions[self.current_index], False

        self.active = False
        return self._generate_feedback(), True

    def cancel(self):
        self.active = False

    def progress(self) -> str:
        return f"{min(self.current_index + 1, len(self.questions))}/{len(self.questions)}"

    def save_transcript(self, path: str = None) -> str:
        path = path or f"interview_{self.role.replace(' ', '_')}_{int(time.time())}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Mock interview transcript — role: {self.role}\n")
            f.write(f"Generated: {datetime.datetime.now().isoformat()}\n\n")
            for i, turn in enumerate(self.transcript, 1):
                f.write(f"Q{i}: {turn['question']}\nA{i}: {turn['answer']}\n\n")
        return path

    # ---- internal ----
    def _generate_questions(self, role):
        prompt = f"""Generate exactly {self.num_questions} realistic job interview questions for someone \
interviewing for a "{role}" position. Mix technical and behavioral questions, ordered from \
easier/warm-up to harder. The candidate is a CS student with AI/ML internship experience, so you \
can reference that background where it fits naturally.

Respond with ONLY a JSON array of {self.num_questions} strings — no markdown, no commentary."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text.strip()
            return self._parse_question_list(text)
        except Exception:
            return self._fallback_questions(role)

    @staticmethod
    def _parse_question_list(text: str):
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()
        questions = json.loads(cleaned)
        if not isinstance(questions, list) or not questions:
            raise ValueError("Model did not return a usable question list")
        return [str(q) for q in questions]

    def _fallback_questions(self, role):
        return [
            f"Tell me about yourself and why you're interested in this {role} role.",
            "Walk me through a challenging project you've worked on.",
            "How do you approach debugging a problem you've never seen before?",
            "Tell me about a time you disagreed with a teammate. How did you handle it?",
            "Do you have any questions for us?"
        ][:self.num_questions]

    def _generate_feedback(self) -> str:
        convo = "\n\n".join(f"Q: {t['question']}\nA: {t['answer']}" for t in self.transcript)
        prompt = f"""Here is a mock interview transcript for a "{self.role}" role:

{convo}

Give brief, constructive overall feedback in 3-4 sentences: one clear strength, one concrete area \
to improve, and one actionable tip. Be encouraging but honest, and speak directly to the candidate."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            return f"Nice work finishing the mock interview, Boss. (Feedback generation failed: {e})"


# ─────────────────────────────────────────
#  SYSTEM COMMANDS
# ─────────────────────────────────────────
def handle_system_command(command: str, voice: VoiceEngine) -> bool:
    """Handle local system commands. Returns True if handled."""

    if any(w in command for w in ["open chrome", "launch chrome", "open browser"]):
        voice.speak("Opening Chrome, Boss.")
        subprocess.Popen(["start", "chrome"], shell=True)
        return True

    if any(w in command for w in ["open notepad", "open notes"]):
        voice.speak("Opening Notepad.")
        subprocess.Popen(["notepad.exe"], shell=True)
        return True

    if any(w in command for w in ["what time is it", "current time", "tell me the time"]):
        now = datetime.datetime.now().strftime("%I:%M %p")
        voice.speak(f"It's {now}, Boss.")
        return True

    if any(w in command for w in ["what's the date", "today's date", "what day is it"]):
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        voice.speak(f"Today is {today}.")
        return True

    if any(w in command for w in ["shutdown", "go to sleep", "goodbye friday", "bye friday"]):
        voice.speak("Signing off. Stay sharp, Boss.")
        sys.exit(0)

    if any(w in command for w in ["clear memory", "forget everything", "reset conversation"]):
        voice.speak("Memory cleared. Starting fresh.")
        return True

    return False


def get_greeting() -> str:
    hour = datetime.datetime.now().hour
    if 5 <= hour < 12:
        period = "Good morning"
    elif 12 <= hour < 17:
        period = "Good afternoon"
    elif 17 <= hour < 21:
        period = "Good evening"
    else:
        period = "Good night"
    return f"{period}, Syed. F.R.I.D.A.Y. is online and ready. How can I assist you?"


# ─────────────────────────────────────────
#  MAIN ASSISTANT ORCHESTRATOR
# ─────────────────────────────────────────
class Friday:
    """on_status(status_str) and on_log(sender, text) are optional GUI hooks.
    status_str is one of: standby, listening, thinking, speaking, interview:i/n"""

    def __init__(self, on_status=None, on_log=None):
        self.on_status = on_status or (lambda s: None)
        self.on_log = on_log or (lambda sender, text: None)

        self.voice = VoiceEngine(on_speak=lambda t: self.on_log("friday", t))
        self.clap = ClapDetector()
        self.speech = SpeechListener()
        self.brain = FridayBrain()
        self.interview = InterviewCoach(self.brain.client)

        self.awake = False
        self.interview_mode = False
        self._pending_interview_role = None   # set via GUI to skip the voice prompt
        self._want_interview_on_wake = False

    # ---- entry points a GUI can call directly ----
    def request_wake(self):
        """Manually wake Friday (e.g. from a GUI button) instead of waiting for a clap."""
        if not self.awake:
            self.clap.manual_trigger.set()

    def request_interview(self, role: str = None):
        """Wake Friday (if needed) and go straight into interview setup."""
        self._want_interview_on_wake = True
        self._pending_interview_role = role
        if self.awake:
            self._start_interview_flow(role)
        else:
            self.clap.manual_trigger.set()

    def stop(self):
        self.awake = False
        self.interview_mode = False
        self.clap.stop()

    # ---- wake / conversation ----
    def wake_up(self):
        print("\n" + "=" * 50)
        print("  F.R.I.D.A.Y. ACTIVATED")
        print("=" * 50)
        self.awake = True

        if self._want_interview_on_wake:
            self._want_interview_on_wake = False
            role = self._pending_interview_role
            self._pending_interview_role = None
            self._start_interview_flow(role)
        else:
            self.on_status("speaking")
            self.voice.speak(get_greeting())

        self._conversation_loop()

    def _listen(self):
        self.on_status("listening")
        return self.speech.listen()

    def _conversation_loop(self):
        if not self.interview_mode:
            self.on_status("speaking")
            self.voice.speak("I'm listening.")
        silence_count = 0

        while self.awake:
            command = self._listen()

            if command is None:
                silence_count += 1
                if silence_count >= 2 and not self.interview_mode:
                    self.on_status("speaking")
                    self.voice.speak("Going back to standby mode. Double clap to wake me.")
                    self.awake = False
                    self.brain.reset_memory()
                    break
                self.on_status("speaking")
                self.voice.speak("I didn't catch that. Please repeat." if not self.interview_mode
                                  else "Take your time — go ahead when you're ready.")
                continue

            silence_count = 0
            self.on_log("you", command)

            # --- interview mode takes priority over everything else ---
            if self.interview_mode:
                if any(p in command for p in INTERVIEW_STOP):
                    self.on_status("speaking")
                    self.voice.speak("Ending the mock interview early. Good effort, Boss.")
                    self.interview_mode = False
                    self.interview.cancel()
                    continue

                self.on_status("thinking")
                next_text, done = self.interview.submit_answer(command)
                if done:
                    self.on_status("speaking")
                    self.voice.speak("Interview complete. Here's my feedback.")
                    self.voice.speak(next_text)
                    self.on_log("system", f"Interview feedback ({self.interview.role}):\n{next_text}")
                    self.interview_mode = False
                else:
                    self.on_status(f"interview:{self.interview.progress()}")
                    self.voice.speak(next_text)
                continue

            # --- sleep/standby ---
            if any(w in command for w in ["go to sleep", "standby", "sleep mode"]):
                self.on_status("speaking")
                self.voice.speak("Entering standby. Double clap to wake me, Boss.")
                self.awake = False
                break

            # --- start an interview from voice, not just the GUI button ---
            if any(p in command for p in INTERVIEW_TRIGGERS):
                self._start_interview_flow()
                continue

            # --- local system commands ---
            if handle_system_command(command, self.voice):
                if "clear memory" in command or "reset" in command:
                    self.brain.reset_memory()
                continue

            # --- fall through to Claude ---
            self.on_status("thinking")
            response = self.brain.think(command)
            self.on_status("speaking")
            self.voice.speak(response)

    def _start_interview_flow(self, role: str = None):
        self.on_status("speaking")
        if not role:
            self.voice.speak("Sure, Boss. What role would you like to practice for?")
            role = self._listen()
            if not role:
                self.on_status("speaking")
                self.voice.speak("I didn't catch a role — let's try again later.")
                return

        self.on_status("speaking")
        self.voice.speak(
            f"Great — a mock interview for {role}. I'll ask you {self.interview.num_questions} "
            f"questions, answer naturally and I'll give you feedback at the end."
        )
        first_question = self.interview.start(role)
        self.interview_mode = True
        self.on_status(f"interview:{self.interview.progress()}")
        self.on_log("system", f"Mock interview started — role: {role}")
        self.voice.speak(first_question)

    # ---- background listening ----
    def start(self):
        """Blocks — runs the clap-wake loop. Call this in a background thread from a GUI."""
        self.on_status("standby")
        try:
            self.clap.listen_for_double_clap(self.wake_up)
        except KeyboardInterrupt:
            self.on_status("speaking")
            self.voice.speak("Shutting down. Goodbye, Boss.")


# ─────────────────────────────────────────
#  CONSOLE ENTRY POINT (no GUI)
# ─────────────────────────────────────────
def _banner():
    print(r"""
  ███████╗██████╗ ██╗██████╗  █████╗ ██╗   ██╗
  ██╔════╝██╔══██╗██║██╔══██╗██╔══██╗╚██╗ ██╔╝
  █████╗  ██████╔╝██║██║  ██║███████║ ╚████╔╝
  ██╔══╝  ██╔══██╗██║██║  ██║██╔══██║  ╚██╔╝
  ██║     ██║  ██║██║██████╔╝██║  ██║   ██║
  ╚═╝     ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝   ╚═╝
        Female Replacement Intelligent Digital Assistant Youth
        Powered by Claude AI | Built for Syed
        Say "mock interview" once awake to start interview practice.
    """)
    print("[F.R.I.D.A.Y.] System initialized. Double clap to activate.\n")


if __name__ == "__main__":
    _banner()
    friday = Friday()
    try:
        friday.start()
    except KeyboardInterrupt:
        sys.exit(0)

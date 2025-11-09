import os
import urllib.request
import random
import pydub
import speech_recognition
import time
import os
import urllib.request
import random
import pydub
import speech_recognition
import time
from typing import Optional
from DrissionPage import ChromiumPage


class RecaptchaSolver:
    """A class to solve reCAPTCHA challenges using audio recognition."""

    # Constants
    TEMP_DIR = os.getenv("TEMP") if os.name == "nt" else "/tmp"
    TIMEOUT_STANDARD = 7
    TIMEOUT_SHORT = 1
    TIMEOUT_DETECTION = 0.05

    def __init__(self, driver: ChromiumPage) -> None:
        """Initialize the solver with a ChromiumPage driver.

        Args:
            driver: ChromiumPage instance for browser interaction
        """
        self.driver = driver

    def solveCaptcha(self, preferred_iframe_index: Optional[int] = None) -> None:
        """Attempt to solve the reCAPTCHA challenge.

        Raises:
            Exception: If captcha solving fails or bot is detected
        """
        # Minimal, fast solver that focuses on reliably clicking the audio
        # button and returning quickly. This keeps the original simple flow
        # but uses a targeted iframe selection that works across variations.
        # Click the main reCAPTCHA checkbox to open the challenge modal.
        self.driver.wait.ele_displayed("@title=reCAPTCHA", timeout=self.TIMEOUT_STANDARD)
        time.sleep(0.1)
        iframe_inner = self.driver("@title=reCAPTCHA")
        iframe_inner.wait.ele_displayed(".rc-anchor-content", timeout=self.TIMEOUT_STANDARD)
        iframe_inner(".rc-anchor-content", timeout=self.TIMEOUT_SHORT).click()

        # If clicking the checkbox already solved it, return immediately.
        # After clicking checkbox, poll briefly for the page token instead of
        # immediately attempting the audio challenge. This avoids unnecessary
        # audio logic when the site already provided a token (common on this page).
        for i in range(6):  # ~6s total (6 * 0.5s)
            print(f"[debug] polling for solved state after checkbox click, attempt {i+1}/6")
            if self.is_solved():
                print("[debug] token detected after checkbox click; skipping audio resolution")
                return
            time.sleep(0.5)

        # Short pause for modal to render if we need to proceed to audio.
        time.sleep(0.4)

        # Try preferred index first (site-specific override), then a targeted
        # XPath that looks for bframe/challenge frames, then a small scan.
        audio_frame = None
        if preferred_iframe_index is not None:
            try:
                pref = self.driver("xpath://iframe", index=preferred_iframe_index, timeout=0.4)
                pref.wait.ele_displayed("#recaptcha-audio-button", timeout=0.5)
                audio_frame = pref
            except Exception:
                pass

        if audio_frame is None:
            # Try a focused XPath that matches challenge/bframe or title hints.
            try:
                candidate = self.driver("xpath://iframe[contains(@src, 'bframe') or contains(translate(@title,'RECAPTCHA','recaptcha'),'recaptcha') or contains(translate(@title,'DESAFIO','desafio'),'desafio') ]", timeout=0.6)
                candidate.wait.ele_displayed("#recaptcha-audio-button", timeout=0.5)
                audio_frame = candidate
            except Exception:
                # Fallback: quick scan of a few top-level iframes
                for i in range(6):
                    try:
                        f = self.driver("xpath://iframe", index=i, timeout=0.3)
                        f.wait.ele_displayed("#recaptcha-audio-button", timeout=0.4)
                        audio_frame = f
                        break
                    except Exception:
                        continue

        if audio_frame is None:
            raise Exception("Audio challenge iframe not found")

        # Click the audio button with a couple quick retries.
        clicked = False
        for _ in range(3):
            try:
                audio_frame("#recaptcha-audio-button", timeout=0.6).click()
                clicked = True
                break
            except Exception:
                time.sleep(0.2)

        if not clicked:
            raise Exception("Could not click #recaptcha-audio-button")

        time.sleep(0.2)
        if self.is_detected():
            raise Exception("Captcha detected bot behavior")

        # After clicking the audio button, verify an audio source actually appeared.
        # Some pages (or solved checkbox) don't present an audio challenge; bail out
        # early in that case to avoid ElementNotFound errors.
        try:
            audio_frame.wait.ele_displayed("#audio-source", timeout=1)
        except Exception:
            print("[debug] no #audio-source found after clicking audio button; assuming no audio challenge")
            return

        # Download/process audio and submit answer (kept minimal).
        src = audio_frame("#audio-source").attrs.get("src")
        if not src:
            raise Exception("No audio source URL found")

        text_response = self._process_audio_challenge(src)
        audio_frame("#audio-response").input(text_response.lower())

        # Try to verify and poll briefly for solved state.
        try:
            audio_frame("#recaptcha-verify-button", timeout=0.8).click()
        except Exception:
            try:
                audio_frame("#audio-response").send_keys('\n')
            except Exception:
                pass

        for _ in range(8):
            if self.is_solved():
                print("[debug] captcha solved")
                return
            time.sleep(0.25)

        raise Exception("Audio challenge failed: not solved after verify")

    def _process_audio_challenge(self, audio_url: str) -> str:
        """Process the audio challenge and return the recognized text.

        Args:
            audio_url: URL of the audio file to process

        Returns:
            str: Recognized text from the audio file
        """
        mp3_path = os.path.join(self.TEMP_DIR, f"{random.randrange(1,1000)}.mp3")
        wav_path = os.path.join(self.TEMP_DIR, f"{random.randrange(1,1000)}.wav")

        try:
            urllib.request.urlretrieve(audio_url, mp3_path)
            sound = pydub.AudioSegment.from_mp3(mp3_path)
            sound.export(wav_path, format="wav")

            recognizer = speech_recognition.Recognizer()
            with speech_recognition.AudioFile(wav_path) as source:
                audio = recognizer.record(source)

            return recognizer.recognize_google(audio)

        finally:
            for path in (mp3_path, wav_path):
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def is_solved(self) -> bool:
        """Check if the captcha has been solved successfully."""
        # Minimal checks focused on values accessible on the main page.
        try:
            print("[debug] is_solved: checking site token #tokenCaptchar")
            try:
                t = self.driver.ele("#tokenCaptchar", timeout=self.TIMEOUT_SHORT)
                val = (getattr(t, 'attrs', {}) or {}).get('value', '') or ''
                if val and str(val).strip():
                    print(f"[debug] is_solved: #tokenCaptchar length={len(val)}")
                    return True
            except Exception:
                # tokenCaptchar not present or inaccessible
                pass

            print("[debug] is_solved: checking g-recaptcha-response textarea")
            try:
                token_el = self.driver.ele(
                    "xpath://textarea[@id='g-recaptcha-response' or @name='g-recaptcha-response']",
                    timeout=self.TIMEOUT_SHORT,
                )
                val = (getattr(token_el, 'attrs', {}) or {}).get('value', '') or ''
                if val and str(val).strip():
                    print(f"[debug] is_solved: g-recaptcha-response length={len(val)}")
                    return True
            except Exception:
                pass

            # As a last resort, try the checkbox mark (inside iframe) but ignore
            # errors — it's often not accessible from main document.
            try:
                el = self.driver.ele(
                    ".recaptcha-checkbox-checkmark", timeout=self.TIMEOUT_SHORT
                )
                if "style" in getattr(el, "attrs", {}):
                    print("[debug] is_solved: checkbox mark indicates solved")
                    return True
            except Exception:
                pass

        except Exception as e:
            print(f"[debug] is_solved: unexpected error: {e}")

        print("[debug] is_solved: not solved")
        return False

    def is_detected(self) -> bool:
        """Check if the bot has been detected."""
        try:
            return (
                self.driver.ele("Try again later", timeout=self.TIMEOUT_DETECTION)
                .states()
                .is_displayed
            )
        except Exception:
            return False

    def get_token(self) -> Optional[str]:
        """Get the reCAPTCHA token if available."""
        try:
            return self.driver.ele("#recaptcha-token").attrs["value"]
        except Exception:
            return None


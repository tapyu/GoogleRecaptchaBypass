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
        
        # Handle main reCAPTCHA iframe
        self.driver.wait.ele_displayed(
            "@title=reCAPTCHA", timeout=self.TIMEOUT_STANDARD
        )
        time.sleep(0.1)
        iframe_inner = self.driver("@title=reCAPTCHA")

        # Click the checkbox
        iframe_inner.wait.ele_displayed(
            ".rc-anchor-content", timeout=self.TIMEOUT_STANDARD
        )
        iframe_inner(".rc-anchor-content", timeout=self.TIMEOUT_SHORT).click()

        # Check if solved by just clicking
        if self.is_solved():
            return

        # Give the modal a moment to appear and the challenge iframes to load.
        # reCAPTCHA often renders the challenge asynchronously; a short sleep
        # reduces race conditions where we try to access iframes too early.
        time.sleep(3.0)

        # If a preferred iframe index was provided (site-specific override), try it first.
        audio_frame = None
        audio_frame_index = None
        audio_frame_attrs = None
        if preferred_iframe_index is not None:
            try:
                print(f"[debug] trying preferred iframe index={preferred_iframe_index}")
                pref = self.driver("xpath://iframe", index=preferred_iframe_index, timeout=self.TIMEOUT_SHORT)
                # if this frame contains the audio button, use it
                pref.wait.ele_displayed("#recaptcha-audio-button", timeout=0.8)
                audio_frame = pref
                audio_frame_index = preferred_iframe_index
                try:
                    el = self.driver.ele("xpath://iframe", index=preferred_iframe_index, timeout=0.2)
                    audio_frame_attrs = getattr(el, 'attrs', {}) or {}
                except Exception:
                    audio_frame_attrs = None
            except Exception:
                print(f"[debug] preferred iframe index={preferred_iframe_index} not usable, falling back to detection")

        # Try to find and click the audio button inside any reCAPTCHA iframe.
        # Some pages embed reCAPTCHA in nested iframes; we'll try a few strategies:
        # 1) enumerate top-level iframes and check for #recaptcha-audio-button
        # 2) if not found, inspect the known @title=reCAPTCHA iframe for nested frames
        audio_frame = None
        audio_frame_index = None
        audio_frame_attrs = None
        max_top_iframes = 12
        # Prefer an iframe whose src contains '/bframe' (challenge frame) if present.
        try:
            for i in range(max_top_iframes):
                try:
                    el = self.driver.ele("xpath://iframe", index=i, timeout=0.2)
                    attrs = getattr(el, 'attrs', {}) or {}
                    src = attrs.get('src', '') or ''
                    title = (attrs.get('title') or '').lower()
                    if 'bframe' in src or 'bframe' in title or 'desafio' in title:
                        try:
                            candidate = self.driver("xpath://iframe", index=i, timeout=0.5)
                            candidate.wait.ele_displayed("#recaptcha-audio-button", timeout=0.5)
                            audio_frame = candidate
                            audio_frame_index = i
                            audio_frame_attrs = attrs
                            break
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass
        for i in range(max_top_iframes):
            try:
                frame = self.driver("xpath://iframe", index=i, timeout=self.TIMEOUT_SHORT)
            except Exception:
                continue
            try:
                # If this frame contains the audio button, use it
                frame.wait.ele_displayed("#recaptcha-audio-button", timeout=0.5)
                # capture attributes for logging
                try:
                    el = self.driver.ele("xpath://iframe", index=i, timeout=0.2)
                    audio_frame_attrs = getattr(el, 'attrs', {}) or {}
                except Exception:
                    audio_frame_attrs = None
                audio_frame = frame
                audio_frame_index = i
                break
            except Exception:
                continue

        # If not found in top-level frames, try inside the @title=reCAPTCHA iframe
        if audio_frame is None:
            try:
                outer = self.driver("@title=reCAPTCHA")
                for j in range(6):
                    try:
                        sub = outer("xpath://iframe", index=j, timeout=self.TIMEOUT_SHORT)
                    except Exception:
                        continue
                    try:
                        sub.wait.ele_displayed("#recaptcha-audio-button", timeout=0.5)
                        try:
                            el = outer.ele("xpath://iframe", index=j, timeout=0.2)
                            audio_frame_attrs = getattr(el, 'attrs', {}) or {}
                        except Exception:
                            audio_frame_attrs = None
                        audio_frame = sub
                        audio_frame_index = f"inner:{j}"
                        break
                    except Exception:
                        continue
            except Exception:
                pass

        # If we found some audio_frame candidate, but the user supplied a
        # preferred_iframe_index, try a short polling loop to wait for the
        # preferred frame to become available. This helps when the preferred
        # challenge frame is still rendering while other frames briefly report
        # the selector.
        if audio_frame is None:
            # Provide a helpful error so the caller can decide (manual, 2captcha, etc.)
            raise Exception("Audio challenge iframe not found — page likely presented an image challenge or iframe indexing differs")

        # If a preferred index was provided but we didn't select it, poll the
        # preferred index for a short time before proceeding. This reduces
        # races where the bframe isn't ready yet but other frames briefly
        # match the selector.
        if preferred_iframe_index is not None and audio_frame_index != preferred_iframe_index:
            print(f"[debug] preferred_index={preferred_iframe_index} provided but selected={audio_frame_index}; polling preferred index for readiness")
            for _ in range(12):  # ~6 seconds total with 0.5s sleep
                try:
                    pref = self.driver("xpath://iframe", index=preferred_iframe_index, timeout=0.5)
                    pref.wait.ele_displayed("#recaptcha-audio-button", timeout=0.5)
                    audio_frame = pref
                    audio_frame_index = preferred_iframe_index
                    try:
                        el = self.driver.ele("xpath://iframe", index=preferred_iframe_index, timeout=0.2)
                        audio_frame_attrs = getattr(el, 'attrs', {}) or {}
                    except Exception:
                        audio_frame_attrs = None
                    print(f"[debug] preferred iframe became ready: index={audio_frame_index}")
                    break
                except Exception:
                    time.sleep(0.5)

        print(f"[debug] selected audio iframe index={audio_frame_index} attrs={audio_frame_attrs}")

        # Click the audio button and proceed. Add logging and retry in case of
        # transient timing/DOM issues.
        try:
            print(f"[debug] attempting to click audio button in detected iframe")
            # Wait a bit for the audio button to appear inside the chosen frame
            audio_frame.wait.ele_displayed("#recaptcha-audio-button", timeout=max(2, self.TIMEOUT_SHORT))
        except Exception:
            # If wait failed, continue and attempt direct click retries below
            pass

        clicked = False
        for attempt in range(3):
            try:
                audio_frame("#recaptcha-audio-button", timeout=max(1, self.TIMEOUT_SHORT)).click()
                clicked = True
                break
            except Exception as e:
                print(f"[debug] click attempt {attempt+1} failed: {e}")
                time.sleep(0.5)

        if not clicked:
            raise Exception("Could not click #recaptcha-audio-button inside detected iframe")

        time.sleep(0.3)

        if self.is_detected():
            raise Exception("Captcha detected bot behavior")

        # Try the audio challenge multiple times in case transcription fails.
        MAX_AUDIO_ATTEMPTS = 3
        last_exception = None
        for audio_attempt in range(1, MAX_AUDIO_ATTEMPTS + 1):
            try:
                print(f"[debug] audio attempt {audio_attempt}/{MAX_AUDIO_ATTEMPTS}")
                # Wait for the audio source to appear
                audio_frame.wait.ele_displayed("#audio-source", timeout=self.TIMEOUT_STANDARD)
                src = audio_frame("#audio-source").attrs.get("src")
                if not src:
                    raise Exception("No audio source URL found")

                text_response = self._process_audio_challenge(src)
                print(f"[debug] recognized audio text: {text_response!r}")
                audio_frame("#audio-response").input(text_response.lower())

                # Click the verify button with retries and then poll for solved state.
                verify_clicked = False
                for attempt in range(6):
                    try:
                        audio_frame.wait.ele_displayed("#recaptcha-verify-button", timeout=1)
                        audio_frame("#recaptcha-verify-button", timeout=1).click()
                        verify_clicked = True
                        print(f"[debug] clicked verify button (attempt {attempt+1})")
                        break
                    except Exception as e:
                        print(f"[debug] verify click attempt {attempt+1} failed: {e}")
                        time.sleep(0.6)

                if not verify_clicked:
                    # Last resort: try to press Enter while focus is on the input
                    try:
                        audio_frame("#audio-response").send_keys('\n')
                        print("[debug] sent Enter key to audio-response as fallback")
                    except Exception:
                        pass

                # Wait/poll for the solved state (give it up to ~8 seconds)
                solved = False
                for _ in range(16):
                    if self.is_solved():
                        solved = True
                        break
                    time.sleep(0.5)

                if solved:
                    print("[debug] captcha solved")
                    return

                # Not solved: log and prepare to retry (request a new audio challenge)
                print(f"[debug] audio attempt {audio_attempt} did not solve the captcha")
                last_exception = Exception("Audio attempt did not solve captcha")

                # Try to request a new audio challenge by clicking the reload button
                try:
                    # common reload selector; if not present, re-click audio button
                    audio_frame("#recaptcha-reload-button", timeout=1).click()
                    print("[debug] clicked #recaptcha-reload-button to get new audio")
                except Exception:
                    try:
                        audio_frame("#recaptcha-audio-button", timeout=1).click()
                        print("[debug] re-clicked #recaptcha-audio-button to refresh audio")
                    except Exception as e:
                        print(f"[debug] failed to refresh audio challenge: {e}")

                # small backoff before next audio attempt
                time.sleep(1.0)

            except Exception as e:
                print(f"[debug] audio attempt {audio_attempt} error: {e}")
                last_exception = e
                time.sleep(1.0)

        # If we exit the attempts loop without returning, raise last exception
        raise Exception(f"Audio challenge failed after {MAX_AUDIO_ATTEMPTS} attempts: {last_exception}")

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
        # Multiple heuristics to detect a solved reCAPTCHA:
        # 1) The checkbox mark element often contains a 'style' attribute once checked.
        # 2) The classic g-recaptcha-response textarea (id or name) may contain a token.
        # 3) A site-specific hidden input (#recaptcha-token) may have the token (get_token()).
        try:
            try:
                el = self.driver.ele(
                    ".recaptcha-checkbox-checkmark", timeout=self.TIMEOUT_SHORT
                )
                if "style" in getattr(el, "attrs", {}):
                    return True
            except Exception:
                # ignore - try other heuristics
                pass

            # Check common g-recaptcha-response textarea by id or name
            try:
                token_el = self.driver.ele(
                    "xpath://textarea[@id='g-recaptcha-response' or @name='g-recaptcha-response']",
                    timeout=self.TIMEOUT_SHORT,
                )
                val = (getattr(token_el, 'attrs', {}) or {}).get('value', '') or ''
                if val and str(val).strip():
                    return True
            except Exception:
                pass

            # Check site-specific token getter
            try:
                tk = self.get_token()
                if tk and str(tk).strip():
                    return True
            except Exception:
                pass

            return False
        except Exception:
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

    def debug_iframes_and_audio_button(self, max_iframes: int = 20, click_checkbox: bool = False) -> None:
        """Print info about top-level iframes and whether they contain the audio button.

        If ``click_checkbox`` is True, the method will attempt to click the main
        reCAPTCHA checkbox first (the usual step that opens the modal). This is
        useful when you want to enumerate iframes after the modal appears.

        This runs via the DrissionPage driver so you can call it from Python (no
        need to open DevTools). It prints index/title/src and whether
        `#recaptcha-audio-button` was found inside that iframe's context.
        """
        # Optionally click the main checkbox to open the modal before
        # enumerating iframes.
        if click_checkbox:
            try:
                print("[debug] clicking main reCAPTCHA checkbox to open modal")
                self.driver.wait.ele_displayed("@title=reCAPTCHA", timeout=self.TIMEOUT_STANDARD)
                iframe_inner = self.driver("@title=reCAPTCHA")
                iframe_inner.wait.ele_displayed(".rc-anchor-content", timeout=self.TIMEOUT_STANDARD)
                iframe_inner(".rc-anchor-content", timeout=self.TIMEOUT_SHORT).click()
                time.sleep(0.6)
            except Exception as e:
                print(f"[debug] failed to click main checkbox: {e}")

        print("[debug] listing up to", max_iframes, "top-level iframes")
        for i in range(max_iframes):
            try:
                el = self.driver.ele("xpath://iframe", index=i, timeout=0.2)
                attrs = getattr(el, 'attrs', {}) or {}
                title = attrs.get('title') or attrs.get('aria-label') or ''
                src = attrs.get('src') or ''
                print(f"[debug] iframe index={i} title={title!r} src={src!r}")
            except Exception:
                # no iframe at this index
                continue

            # Try to create a frame context and check for the audio button
            try:
                frame_ctx = self.driver("xpath://iframe", index=i, timeout=0.5)
                try:
                    frame_ctx.wait.ele_displayed("#recaptcha-audio-button", timeout=0.5)
                    exists = True
                except Exception:
                    exists = False
                print(f"[debug] -> #recaptcha-audio-button present in iframe index={i}: {exists}")
            except Exception as e:
                print(f"[debug] -> cannot access iframe context index={i}: {e}")

        print("[debug] enumeration complete")
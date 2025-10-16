import json
import logging
import os
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import tweepy
import requests
from dotenv import load_dotenv

from ai_core import build_qa_chain
from db import save_chat, get_chat_history
from responses import ASKA_NO_DATA_RESPONSE, ASKA_TECHNICAL_ISSUE_RESPONSE
from utils import (
    coerce_to_text,
    format_history_for_chain,
    normalize_input,
    remove_trailing_signature,
    replace_bot_mentions,
    rewrite_schedule_query,
    strip_markdown,
    is_substantive_text,
    current_jakarta_time,
    format_indonesian_date,
    INDONESIAN_DAY_NAMES,
)

LOGGER = logging.getLogger("aska.twitter")

DEFAULT_SPAM_KEYWORDS = {
    "follow back", "folback", "promo", "promote", "dm for collab",
    "shoutout", "boost me", "subscribe", "retweet this",
    "please follow", "follow me",
}


def _load_required_env(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"Environment variable '{key}' is required for Twitter integration.")
    return v


def _parse_tweepy_error(exc) -> Dict[str, Any]:
    """Ambil status/text/codes dari Tweepy Exception untuk diagnosa & fallback."""
    data = {"status": None, "text": None, "codes": []}
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            data["status"] = getattr(resp, "status_code", None)
            try:
                data["text"] = resp.text
            except Exception:
                data["text"] = None
            try:
                j = resp.json()
                errs = j.get("errors") or []
                for e in errs:
                    c = e.get("code")
                    if c is not None:
                        data["codes"].append(int(c))
            except Exception:
                pass
    except Exception:
        pass
    return data


class TwitterAskaBot:
    def __init__(self) -> None:
        load_dotenv()
        logging.basicConfig(
            level=os.getenv("TWITTER_LOG_LEVEL", "INFO"),
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        )

        # Runtime/env
        self.poll_interval = int(os.getenv("TWITTER_POLL_INTERVAL", "180"))
        self.state_path = Path(os.getenv("TWITTER_STATE_PATH", "twitter_state.json"))

        # Autopost config
        self.autopost_enabled = os.getenv("TWITTER_AUTOPOST_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.autopost_interval = int(os.getenv("TWITTER_AUTOPOST_INTERVAL", "3600"))
        self.autopost_recent_limit = max(1, int(os.getenv("TWITTER_AUTOPOST_RECENT_LIMIT", "8")))
        self.autopost_entries_path = Path(os.getenv("TWITTER_AUTOPOST_MESSAGES_PATH", "twitter_posts.txt"))
        self.autopost_force_on_start = os.getenv("TWITTER_AUTOPOST_FORCE_ON_START", "false").strip().lower() in {"1", "true", "yes", "on"}
        self._autopost_log_state = None

        # Mentions control
        self.mentions_enabled = os.getenv("TWITTER_MENTIONS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.mentions_cooldown = int(os.getenv("TWITTER_MENTIONS_COOLDOWN", "180"))
        self.mentions_max_results = int(os.getenv("TWITTER_MENTIONS_MAX_RESULTS", "5"))
        self.mentions_latest_only = os.getenv("TWITTER_MENTIONS_LATEST_ONLY", "false").strip().lower() in {"1", "true", "yes", "on"}
        self._mentions_backoff_until = 0.0
        self._mentions_backoff_last = self.mentions_cooldown

        # Spam cfg (permisif)
        self.spam_keywords = self._load_spam_keywords()

        LOGGER.info("Initializing ASKA Twitter bot…")
        self._client = self._build_client()

        me = self._client.get_me()
        if not me or not me.data:
            raise RuntimeError("Failed to fetch bot account details from Twitter API.")
        self.bot_user_id = int(me.data.id)
        self.bot_username = me.data.username.lower()
        LOGGER.info("Authenticated as @%s (id=%s)", self.bot_username, self.bot_user_id)

        # Build RAG chain
        self.qa_chain = build_qa_chain()
        try:
            schema = getattr(self.qa_chain, "input_schema", None)
            props: Dict[str, Any] = {}
            if schema:
                mj = getattr(schema, "model_json_schema", None)
                if callable(mj):
                    props = mj().get("properties", {})
                else:
                    legacy = getattr(schema, "schema", None)
                    if callable(legacy):
                        props = legacy().get("properties", {})
            LOGGER.info("QA chain input vars detected: %s", list(props.keys()) or ["<unknown>"])
        except Exception:
            LOGGER.info("QA chain input vars could not be introspected; using heuristics.")

        # Load autopost entries
        self.autopost_entries = self._load_autopost_entries()
        try:
            resolved_path = str(self.autopost_entries_path.resolve())
        except Exception:
            resolved_path = str(self.autopost_entries_path)
        LOGGER.info(
            "Autopost status: enabled=%s interval=%ss entries=%d path=%s",
            self.autopost_enabled, self.autopost_interval, len(self.autopost_entries), resolved_path
        )

        # Persisted state
        state = self._load_state()
        self.last_seen_id = state.get("last_seen_id")
        defaults = {"next_index": 0, "last_timestamp": 0.0, "recent_hashes": []}
        self.autopost_state: Dict[str, Any] = {**defaults, **state.get("autopost", {})}
        if not isinstance(self.autopost_state.get("recent_hashes"), list):
            self.autopost_state["recent_hashes"] = []

        # Warm-up once on start (can force ignore interval)
        try:
            if self.autopost_enabled:
                LOGGER.info("Autopost warm-up: trying one shot on startup…")
                self._maybe_autopost(ignore_interval=self.autopost_force_on_start)
        except Exception:
            LOGGER.exception("Warm-up autopost failed")

    def _build_client(self) -> tweepy.Client:
        bearer = _load_required_env("TWITTER_BEARER_TOKEN")
        api_key = _load_required_env("TWITTER_API_KEY")
        api_secret = _load_required_env("TWITTER_API_SECRET")
        access_token = _load_required_env("TWITTER_ACCESS_TOKEN")
        access_secret = _load_required_env("TWITTER_ACCESS_SECRET")
        wait_on = os.getenv("TWITTER_WAIT_ON_RATE_LIMIT", "false").strip().lower() in {"1", "true", "yes", "on"}
        return tweepy.Client(
            bearer_token=bearer,
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
            wait_on_rate_limit=wait_on,  # False direkomendasikan: manual backoff
        )

    # ── State ──────────────────────────────────────────────
    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            with self.state_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            LOGGER.warning("Unable to read state file %s: %s", self.state_path, exc)
            return {}
        if not isinstance(payload, dict):
            LOGGER.warning("Unexpected state file format, resetting state.")
            return {}

        raw_last_seen = payload.get("last_seen_id")
        if raw_last_seen is not None:
            try:
                payload["last_seen_id"] = int(raw_last_seen)
            except (TypeError, ValueError):
                LOGGER.warning("Invalid last_seen_id '%s' in state file, ignoring.", raw_last_seen)
                payload.pop("last_seen_id", None)

        autopost_state = payload.get("autopost")
        if isinstance(autopost_state, dict):
            if "next_index" in autopost_state:
                try:
                    autopost_state["next_index"] = int(autopost_state["next_index"])
                except (TypeError, ValueError):
                    autopost_state.pop("next_index", None)
            if "last_timestamp" in autopost_state:
                try:
                    autopost_state["last_timestamp"] = float(autopost_state["last_timestamp"])
                except (TypeError, ValueError):
                    autopost_state.pop("last_timestamp", None)
            hashes = autopost_state.get("recent_hashes")
            if isinstance(hashes, list):
                autopost_state["recent_hashes"] = [str(h) for h in hashes if isinstance(h, (str, int)) and str(h).strip()]
            else:
                autopost_state["recent_hashes"] = []
        return payload

    def _persist_state(self) -> None:
        try:
            payload = {"last_seen_id": self.last_seen_id, "autopost": self.autopost_state}
            with self.state_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception as exc:
            LOGGER.error("Unable to persist state file %s: %s", self.state_path, exc)

    # ── Loop ───────────────────────────────────────────────
    def run(self) -> None:
        LOGGER.info("Starting polling loop (interval=%s seconds)", self.poll_interval)
        if self.autopost_enabled:
            self._maybe_autopost(ignore_interval=False)
        while True:
            try:
                if self.mentions_enabled and time.time() >= self._mentions_backoff_until:
                    self.process_mentions()
                elif not self.mentions_enabled:
                    LOGGER.debug("Mentions disabled by env; skipping.")
                else:
                    remain = int(self._mentions_backoff_until - time.time())
                    if remain > 0:
                        LOGGER.info("Mentions backoff active (%ss remaining); skipping this cycle.", remain)

                if self.autopost_enabled:
                    self._maybe_autopost(ignore_interval=False)
            except Exception:
                LOGGER.exception("Unexpected error while processing cycle")
            time.sleep(self.poll_interval)

    # ── Mentions ───────────────────────────────────────────
    def process_mentions(self) -> None:
        if time.time() < self._mentions_backoff_until:
            remain = int(self._mentions_backoff_until - time.time())
            LOGGER.info("Mentions backoff still active (%ss); skip.", remain)
            return

        # API mensyaratkan 5..100
        if self.mentions_latest_only:
            requested_max = 5
        else:
            requested_max = max(5, min(self.mentions_max_results, 100))

        params = {
            "tweet_fields": ["author_id", "created_at"],
            "expansions": ["author_id"],
            "since_id": self.last_seen_id,
            "max_results": requested_max,
        }

        try:
            response = self._client.get_users_mentions(self.bot_user_id, **params)
            # sukses → reset backoff dasar
            self._mentions_backoff_last = self.mentions_cooldown
        except tweepy.TooManyRequests as exc:
            base = self.mentions_cooldown
            last = getattr(self, "_mentions_backoff_last", base)
            cool = min(max(base, last * 2), int(os.getenv("TWITTER_MENTIONS_MAX_COOLDOWN", "900")))
            try:
                reset_at = int(exc.response.headers.get("x-rate-limit-reset", "0"))
                now = int(time.time())
                if reset_at > now:
                    cool = max(30, min(reset_at - now, 900))
            except Exception:
                pass
            import random
            cool += int(cool * random.uniform(0, 0.1))  # jitter
            self._mentions_backoff_last = cool
            self._mentions_backoff_until = time.time() + cool
            LOGGER.warning("Mentions rate-limited (429). Backing off for %ss (jittered).", cool)
            return
        except tweepy.BadRequest as exc:
            LOGGER.warning("Mentions 400 Bad Request: %s. Retrying once with max_results=5.", exc)
            params["max_results"] = 5
            try:
                response = self._client.get_users_mentions(self.bot_user_id, **params)
                self._mentions_backoff_last = self.mentions_cooldown
            except Exception as exc2:
                LOGGER.warning("Mentions fallback failed: %s", exc2)
                return
        except (tweepy.TweepyException, requests.RequestException) as exc:
            LOGGER.warning("Failed to fetch mentions (retry next cycle): %s", exc)
            return

        tweets = response.data or []
        if not tweets:
            LOGGER.debug("No new mentions found.")
            return

        # Build user map
        user_map: Dict[int, str] = {}
        includes = getattr(response, "includes", None)
        if includes and isinstance(includes, dict):
            for u in includes.get("users") or []:
                try:
                    uid = int(getattr(u, "id", 0) or 0)
                    uname = getattr(u, "username", None)
                    if uid and uname:
                        user_map[uid] = str(uname)
                except Exception:
                    pass

        if self.mentions_latest_only:
            try:
                latest = max(tweets, key=lambda t: getattr(t, "created_at", None) or datetime.min)
            except Exception:
                latest = max(tweets, key=lambda t: int(t.id))
            tweets_to_process = [latest]
            LOGGER.info("Processing latest mention only: %s", latest.id)
        else:
            tweets_to_process = list(reversed(tweets))
            LOGGER.info("Processing %d new mentions", len(tweets_to_process))

        for tweet in tweets_to_process:
            self._handle_tweet(tweet, user_map)

        newest_id = response.meta.get("newest_id") if response.meta else None
        try:
            if self.mentions_latest_only and tweets_to_process:
                newest_id = str(tweets_to_process[0].id)
        except Exception:
            pass
        if newest_id:
            self.last_seen_id = int(newest_id)
            self._persist_state()

    def _handle_tweet(self, tweet: tweepy.Tweet, user_map: Optional[Dict[int, str]] = None) -> None:
        if int(tweet.author_id) == self.bot_user_id:
            LOGGER.debug("Skipping self mention tweet %s", tweet.id)
            return

        username = None
        try:
            if user_map:
                username = user_map.get(int(tweet.author_id))
        except Exception:
            username = None

        raw_text = tweet.text or ""
        cleaned = replace_bot_mentions(raw_text, self.bot_username)
        LOGGER.debug(
            "Mention raw='%s' | cleaned='%s' | len=%d",
            raw_text.replace("\n", " "),
            (cleaned or "").replace("\n", " "),
            len(cleaned or ""),
        )

        if self._is_spam_content(username, raw_text, cleaned):
            LOGGER.info("Skipping spam/empty mention from @%s (%s)", username, tweet.id)
            return

        LOGGER.info("Mention from @%s: %s", username, raw_text.replace("\n", " "))
        user_id = int(tweet.author_id)

        try:
            save_chat(user_id, username, raw_text, role="user", topic="twitter")
        except Exception:
            LOGGER.exception("Failed to persist incoming tweet %s to chat history", tweet.id)

        reply_text = self._generate_reply(user_id, cleaned)
        prefix = f"@{username} " if username else ""
        status = (prefix + reply_text)[:280]

        try:
            self._client.create_tweet(text=status, in_reply_to_tweet_id=tweet.id)
            LOGGER.info("Replied to tweet %s", tweet.id)
        except tweepy.Forbidden as exc:
            info = _parse_tweepy_error(exc)
            LOGGER.warning(
                "Reply forbidden for tweet %s (status=%s, codes=%s). Raw=%s",
                tweet.id, info["status"], info["codes"], info["text"]
            )
            codes = set(info["codes"] or [])
            if 385 in codes:
                # Not allowed to reply to this Tweet (privacy who-can-reply)
                try:
                    qt = (prefix + reply_text)[:280]
                    self._client.create_tweet(text=qt, quote_tweet_id=tweet.id)
                    LOGGER.info("Quote-tweeted instead for %s", tweet.id)
                except Exception:
                    try:
                        nt = (prefix + reply_text)[:280]
                        self._client.create_tweet(text=nt)
                        LOGGER.info("Posted normal mention instead for %s", tweet.id)
                    except Exception:
                        LOGGER.exception("Failed all fallbacks for tweet %s", tweet.id)
                        return
            elif 187 in codes:
                # Duplicate content
                try:
                    from datetime import datetime as _dt
                    suffix = " · " + _dt.now().strftime("%H:%M:%S")
                    dedup = (status[: (280 - len(suffix))] + suffix)
                    self._client.create_tweet(text=dedup, in_reply_to_tweet_id=tweet.id)
                    LOGGER.info("Replied after de-duplicating content for %s", tweet.id)
                except Exception:
                    LOGGER.exception("Failed to resend non-duplicate reply for %s", tweet.id)
                    return
            else:
                # Generic fallback
                try:
                    qt = (prefix + reply_text)[:280]
                    self._client.create_tweet(text=qt, quote_tweet_id=tweet.id)
                    LOGGER.info("Quote-tweeted (generic fallback) for %s", tweet.id)
                except Exception:
                    try:
                        nt = (prefix + reply_text)[:280]
                        self._client.create_tweet(text=nt)
                        LOGGER.info("Posted normal mention (generic fallback) for %s", tweet.id)
                    except Exception:
                        LOGGER.exception("Failed generic fallbacks for tweet %s", tweet.id)
                        return
        except Exception:
            LOGGER.exception("Failed to send reply for tweet %s", tweet.id)
            return

        try:
            save_chat(user_id, "ASKA", reply_text, role="aska", topic="twitter")
        except Exception:
            LOGGER.exception("Failed to persist ASKA reply for tweet %s", tweet.id)
        finally:
            self._persist_state()

    # ── Chain wrapper (SELALU kirim chat_history) ──────────
    def _invoke_chain(self, prompt: str, chat_history):
        # Introspeksi best-effort
        input_vars = set()
        try:
            schema = getattr(self.qa_chain, "input_schema", None)
            if schema:
                mj = getattr(schema, "model_json_schema", None)
                if callable(mj):
                    props = mj().get("properties", {})
                else:
                    legacy = getattr(schema, "schema", None)
                    props = legacy().get("properties", {}) if callable(legacy) else {}
                input_vars = set(props.keys())
        except Exception:
            pass

        payload: Dict[str, Any] = {}
        for k in ("input", "question", "query"):
            if k in input_vars:
                payload[k] = prompt
                break
        else:
            payload["input"] = prompt  # default
        payload["chat_history"] = chat_history  # ALWAYS include

        try:
            return self.qa_chain.invoke(payload)
        except KeyError as e:
            if "Expected:" in str(e):
                payload.setdefault("history", chat_history)
                payload.setdefault("messages", chat_history)
                return self.qa_chain.invoke(payload)
            raise

    # --- Helper (taruh di dalam class TwitterAskaBot) ----------------------------
    def _twitter_target_len(self) -> int:
        try:
            return max(80, int(os.getenv("ASKA_TWITTER_MAX_CHARS", "200")))
        except Exception:
            return 200

    def _smart_trim(self, text: str, limit: int) -> str:
        """Potong teks dengan rapi (prioritas titik, lalu spasi), tambahkan '...' jika dipotong."""
        if len(text) <= limit:
            return text
        cut = text[: max(0, limit - 3)]
        # cari akhir kalimat yang masuk akal
        end = cut.rfind(".")
        if end >= int(0.6 * limit):
            return cut[: end + 1].rstrip() + " ..."
        # kalau tidak ada titik, coba spasi
        end = cut.rfind(" ")
        if end >= int(0.6 * limit):
            return cut[: end].rstrip() + " ..."
        return cut.rstrip() + "..."


    # --- GANTI fungsi ini dengan versi di bawah ----------------------------------
    def _generate_reply(self, user_id: int, message: str) -> str:
        normalized = normalize_input(message)
        normalized = rewrite_schedule_query(normalized)

        # ⬇️ Suntikkan instruksi "jawab ringkas" khusus Twitter
        if os.getenv("ASKA_TWITTER_MODE", "true").strip().lower() in {"1", "true", "on"}:
            target = self._twitter_target_len()
            normalized = (
                "Jawablah SANGAT RINGKAS (maksimal "
                f"{target} karakter), bahasa Indonesia sederhana, langsung ke inti, "
                "tanpa markdown/emoji/daftar/basa-basi. "
                f"Pertanyaan: {normalized}"
            )

        history = []
        try:
            history = get_chat_history(user_id, limit=5)
        except Exception:
            LOGGER.exception("Failed to fetch chat history for user %s", user_id)

        chat_history = format_history_for_chain(history)
        try:
            result = self._invoke_chain(normalized, chat_history)
            raw = (coerce_to_text(result) or "").strip()
            try:
                cleaned = strip_markdown(remove_trailing_signature(raw)).strip()
            except Exception:
                cleaned = raw
            response = cleaned or raw or ""
            if not response:
                return ASKA_NO_DATA_RESPONSE

            # ⬇️ Pastikan tidak melewati batas karakter yang kamu inginkan untuk Twitter
            #    (batasi sesuai target ringkas + batas tweet)
            target = self._twitter_target_len()
            try:
                max_tweet = max(140, int(os.getenv("TWITTER_MAX_TWEET_LEN", "280")))
            except Exception:
                max_tweet = 280
            hard_limit = min(target, max_tweet)  # misal 200 ↔︎ 280
            response = self._smart_trim(response, hard_limit)

            return response or ASKA_NO_DATA_RESPONSE
        except Exception:
            LOGGER.exception("Failed to generate ASKA reply for user %s", user_id)
            return ASKA_TECHNICAL_ISSUE_RESPONSE
                
    # ── Autopost ───────────────────────────────────────────
    def _load_autopost_entries(self) -> List[Dict[str, Any]]:
        if not self.autopost_enabled:
            return []
        if not self.autopost_entries_path.exists():
            LOGGER.warning("Auto-post enabled but messages file %s not found.", self.autopost_entries_path)
            return []
        try:
            content = self.autopost_entries_path.read_text(encoding="utf-8")
        except Exception as exc:
            LOGGER.error("Failed to read auto-post messages file: %s", exc)
            return []

        entries: List[Dict[str, Any]] = []
        for line in content.splitlines():
            raw_line = line.strip()
            if not raw_line or raw_line.startswith("#"):
                continue
            if raw_line.lower().startswith("rag:"):
                prompt = raw_line[4:].strip()
                if prompt:
                    entries.append({"mode": "rag", "prompt": prompt, "raw": raw_line})
                else:
                    LOGGER.warning("Ignoring RAG auto-post entry with empty prompt: %s", raw_line)
            else:
                entries.append({"mode": "static", "text": raw_line, "raw": raw_line})
        if not entries:
            LOGGER.warning("Auto-post messages file %s is empty after filtering.", self.autopost_entries_path)
        return entries

    def _maybe_autopost(self, *, ignore_interval: bool = False) -> None:
        if not self.autopost_entries:
            if self._autopost_log_state != "empty":
                LOGGER.info("Auto-post skipped: no messages loaded.")
                self._autopost_log_state = "empty"
            return

        now_ts = time.time()
        last_ts = float(self.autopost_state.get("last_timestamp") or 0)

        if not ignore_interval:
            if now_ts - last_ts < self.autopost_interval:
                remain = int(self.autopost_interval - (now_ts - last_ts))
                LOGGER.info("Auto-post skipped: interval gate (%ss remaining).", remain)
                return
        else:
            LOGGER.info("Auto-post running with ignore_interval=True (forced on start).")

        total_entries = len(self.autopost_entries)
        if total_entries == 0:
            LOGGER.info("Auto-post skipped: entries=0.")
            return

        next_index = int(self.autopost_state.get("next_index") or 0)
        entry = self.autopost_entries[next_index % total_entries]
        message = self._render_autopost_entry(entry)

        if not message:
            LOGGER.warning("Auto-post entry at index %s produced no content; skipping.", next_index)
            self.autopost_state["next_index"] = (next_index + 1) % total_entries
            self.autopost_state["last_timestamp"] = now_ts
            self._autopost_log_state = "empty"
            self._persist_state()
            return

        message = self._apply_placeholders(" ".join(message.split()))
        if len(message) > 280:
            LOGGER.warning("Auto-post message at index %s exceeds 280 chars, truncating.", next_index)
            message = message[:280]

        message_hash = self._hash_message(message)
        recent_hashes = list(self.autopost_state.get("recent_hashes") or [])
        if message_hash in recent_hashes:
            LOGGER.warning("Auto-post duplicate detected at index %s (mode=%s); skipping.", next_index, entry.get("mode", "static"))
            self.autopost_state["next_index"] = (next_index + 1) % total_entries
            self.autopost_state["last_timestamp"] = now_ts
            self._autopost_log_state = "duplicate"
            self._persist_state()
            return

        LOGGER.debug("Auto-post candidate ready (index=%s, mode=%s, length=%s): %s",
                     next_index, entry.get("mode", "static"), len(message), message)

        try:
            self._client.create_tweet(text=message)
            LOGGER.info("Auto-posted tweet (index=%s, mode=%s).", next_index, entry.get("mode", "static"))
        except Exception:
            LOGGER.exception("Failed to auto-post tweet at index %s (mode=%s, preview=%r)",
                             next_index, entry.get("mode", "static"), message[:160])
            return

        recent_hashes.append(message_hash)
        if len(recent_hashes) > self.autopost_recent_limit:
            recent_hashes = recent_hashes[-self.autopost_recent_limit:]
        self.autopost_state["recent_hashes"] = recent_hashes
        self.autopost_state["next_index"] = (next_index + 1) % total_entries
        self.autopost_state["last_timestamp"] = now_ts
        self._autopost_log_state = "posted"
        self._persist_state()

    def _render_autopost_entry(self, entry: Dict[str, Any]) -> Optional[str]:
        if not entry:
            return None
        mode = entry.get("mode", "static")

        if mode == "static":
            text = str(entry.get("text", "")).strip()
            return text if text else None

        if mode == "rag":
            prompt = entry.get("prompt")
            if not prompt:
                return None
            prompt = self._apply_placeholders(str(prompt))
            try:
                result = self._invoke_chain(prompt, [])
                raw = (coerce_to_text(result) or "").strip()
                try:
                    cleaned = strip_markdown(remove_trailing_signature(raw)).strip()
                except Exception:
                    cleaned = raw
                response = " ".join((cleaned or raw).split()).strip()
                return response or None
            except Exception:
                LOGGER.exception("Failed to build RAG auto-post for prompt: %s", prompt)
                return None
        return None

    # ── Utils ──────────────────────────────────────────────
    def _apply_placeholders(self, text: Optional[str]) -> str:
        if text is None:
            return ""
        value = str(text)
        try:
            now = current_jakarta_time()
            if not isinstance(now, datetime):
                raise TypeError
        except Exception:
            now = datetime.now()

        try:
            day_name = INDONESIAN_DAY_NAMES.get(now.weekday(), now.strftime("%A"))
        except Exception:
            day_name = now.strftime("%A")

        try:
            date_label = format_indonesian_date(now)
        except Exception:
            date_label = now.strftime("%Y-%m-%d")

        time_label = now.strftime("%H:%M WIB")
        stamp = now.strftime("%Y%m%d%H%M%S")
        epoch = str(int(now.timestamp()))

        replacements = {
            "{{DAY}}": day_name,
            "{{DATE}}": date_label,
            "{{TIME}}": time_label,
            "{{DATETIME}}": f"{day_name}, {date_label} {time_label}",
            "{{STAMP}}": stamp,
            "{{UNIQUE}}": stamp,
            "{{EPOCH}}": epoch,
        }
        for k, v in replacements.items():
            value = value.replace(k, v)
        return value

    def _hash_message(self, message: str) -> str:
        normalized = (message or "").strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def _load_spam_keywords(self) -> set:
        raw = os.getenv("TWITTER_SPAM_KEYWORDS", "")
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    # ── Spam filter PERMISIF (tanpa whitelist) ─────────────
    def _is_spam_content(self, username: Optional[str], raw_text: str, cleaned_text: str) -> bool:
        """
        - TWITTER_SPAM_DISABLE=true  -> semua lolos.
        - Ada tanda tanya (?)        -> lolos (indikasi pertanyaan).
        - Panjang/kata cukup         -> lolos.
        - Tetap blokir keyword spam (default/env).
        - Strict mode hanya blokir jika sangat pendek & tanpa '?'.
        """
        if os.getenv("TWITTER_SPAM_DISABLE", "false").strip().lower() in {"1", "true", "yes", "on"}:
            return False

        raw = (raw_text or "")
        cleaned = (cleaned_text or "").strip()
        strict = os.getenv("TWITTER_SPAM_FILTER_STRICT", "false").strip().lower() in {"1", "true", "yes", "on"}

        try:
            min_chars = max(1, int(os.getenv("TWITTER_SPAM_MIN_CHARS", "2")))
        except Exception:
            min_chars = 2
        try:
            min_words = max(1, int(os.getenv("TWITTER_SPAM_MIN_WORDS", "1")))
        except Exception:
            min_words = 1

        # pertanyaan → allow
        if "?" in raw or "?" in cleaned:
            LOGGER.debug("Spam check: has '?', allow.")
            return False

        words = [w for w in cleaned.split() if any(ch.isalnum() for ch in w)]
        has_alnum = any(ch.isalnum() for ch in cleaned)

        if (len(cleaned) >= min_chars and has_alnum) or (len(words) >= min_words):
            LOGGER.debug("Spam check: content-length ok (len=%d, words=%d), allow.", len(cleaned), len(words))
        else:
            if strict:
                LOGGER.info("Spam check: too short (len=%d, words=%d) in strict mode -> block.", len(cleaned), len(words))
                return True
            else:
                if has_alnum:
                    LOGGER.debug("Spam check: short but has alnum (non-strict), allow.")
                else:
                    LOGGER.info("Spam check: no alnum -> block.")
                    return True

        haystack = f"{raw} {cleaned}".lower()
        for token in DEFAULT_SPAM_KEYWORDS:
            if token and token in haystack:
                LOGGER.info("Spam check: matched default spam keyword '%s' -> block.", token)
                return True
        for token in self.spam_keywords:
            if token and token in haystack:
                LOGGER.info("Spam check: matched custom spam keyword '%s' -> block.", token)
                return True

        LOGGER.debug("Spam check: accepted.")
        return False


if __name__ == "__main__":
    bot = TwitterAskaBot()
    bot.run()

"""Auto reply command implementation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List

from telethon import events

from .base import ActiveCommand, CommandContext, UserbotCommand


@dataclass
class _AutoReplyState:
    keywords: List[str]
    exclusions: List[str]
    reply_text: str
    me_id: int | None
    keyword_match_type: str = "contains"
    keyword_logic: str = "any"
    exclusion_match_type: str = "contains"
    exclusion_logic: str = "any"
    counter: int = 0
    _keyword_checks: List[Callable[[str, str], bool]] | None = None
    _exclusion_checks: List[Callable[[str, str], bool]] | None = None

    def __post_init__(self) -> None:
        self._keyword_checks = [self._make_checker(word, self.keyword_match_type) for word in self.keywords]
        self._exclusion_checks = [self._make_checker(word, self.exclusion_match_type) for word in self.exclusions]

    def _make_checker(self, word: str, mode: str) -> Callable[[str, str], bool]:
        if mode == "specific":
            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            return lambda original, _lowered: bool(pattern.search(original))
        lowered_word = word.lower()
        return lambda _original, lowered: lowered_word in lowered

    def match(self, text: str) -> bool:
        lowered = text.lower()
        keyword_hits = [check(text, lowered) for check in (self._keyword_checks or [])]
        if not keyword_hits:
            return False

        if self.keyword_logic == "all":
            keywords_ok = all(keyword_hits)
        else:
            keywords_ok = any(keyword_hits)

        if not keywords_ok:
            return False

        if not self._exclusion_checks:
            return True

        exclusion_hits = [check(text, lowered) for check in self._exclusion_checks]
        if self.exclusion_logic == "all":
            blocked = all(exclusion_hits)
        else:
            blocked = any(exclusion_hits)

        return not blocked


class AutoReplyCommand(UserbotCommand):
    def __init__(self) -> None:
        super().__init__(slug="auto_reply")

    async def start(self, ctx: CommandContext) -> ActiveCommand | None:
        logger = ctx.logger
        details = ctx.details
        targets = details.get("targets") or []
        keywords = [str(item).strip().lower() for item in details.get("keywords", []) if str(item).strip()]
        exclusions = [str(item).strip().lower() for item in details.get("exclusions", []) if str(item).strip()]
        reply_text = (details.get("reply_text") or "").strip()
        keyword_match_type = str(details.get("keyword_match_type") or "contains").lower()
        keyword_logic = str(details.get("keyword_logic") or "any").lower()
        exclusion_match_type = str(details.get("exclusion_match_type") or "contains").lower()
        exclusion_logic = str(details.get("exclusion_logic") or "any").lower()

        if not targets or not keywords or not reply_text:
            logger.error("Data auto reply belum lengkap. targets=%s keywords=%s reply=%s", targets, keywords, bool(reply_text))
            await ctx.update_status("error", "Input auto reply tidak lengkap.")
            return None

        me = await ctx.client.get_me()
        state = _AutoReplyState(
            keywords=keywords,
            exclusions=exclusions,
            reply_text=reply_text,
            me_id=getattr(me, "id", None),
            keyword_match_type="specific" if keyword_match_type == "specific" else "contains",
            keyword_logic="all" if keyword_logic == "all" else "any",
            exclusion_match_type="specific" if exclusion_match_type == "specific" else "contains",
            exclusion_logic="all" if exclusion_logic == "all" else "any",
        )

        handler = events.NewMessage(chats=targets)

        async def _on_message(event: events.NewMessage.Event) -> None:
            if event.out:
                return
            if state.me_id and event.sender_id == state.me_id:
                return
            message_text = event.raw_text or ""
            if not message_text:
                return
            if not state.match(message_text):
                return
            try:
                await event.reply(reply_text)
                state.counter += 1
                logger.info(
                    "Auto reply terkirim ke %s (process_id=%s, total=%s)",
                    event.chat_id,
                    ctx.process_id,
                    state.counter,
                )
                await ctx.refresh_task_details({"replied_count": state.counter})
            except Exception as exc:  # pragma: no cover - jaringan
                logger.exception("Gagal mengirim auto reply: %s", exc)

        ctx.client.add_event_handler(_on_message, handler)
        logger.info(
            "Auto reply aktif pada %s dengan %s kata kunci (process_id=%s)",
            len(targets),
            len(keywords),
            ctx.process_id,
        )
        await ctx.update_status("running", None)

        active = ActiveCommand()

        async def _remove_handler() -> None:
            try:
                ctx.client.remove_event_handler(_on_message, handler)
            except ValueError:
                pass

        active.add_stop_callback(_remove_handler)
        return active


def build_command() -> UserbotCommand:
    return AutoReplyCommand()

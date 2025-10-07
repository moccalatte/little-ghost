"""Auto reply command implementation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from telethon import events

from .base import ActiveCommand, CommandContext, UserbotCommand


@dataclass
class _AutoReplyState:
    keywords: List[str]
    exclusions: List[str]
    reply_text: str
    me_id: int | None
    counter: int = 0

    def match(self, text: str) -> bool:
        lowered = text.lower()
        if any(keyword in lowered for keyword in self.keywords):
            if self.exclusions and any(word in lowered for word in self.exclusions):
                return False
            return True
        return False


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

        if not targets or not keywords or not reply_text:
            logger.error("Data auto reply belum lengkap. targets=%s keywords=%s reply=%s", targets, keywords, bool(reply_text))
            await ctx.update_status("error", "Input auto reply tidak lengkap.")
            return None

        me = await ctx.client.get_me()
        state = _AutoReplyState(keywords=keywords, exclusions=exclusions, reply_text=reply_text, me_id=getattr(me, "id", None))

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

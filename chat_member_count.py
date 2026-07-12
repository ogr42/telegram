__id__ = "chat_member_count"
__name__ = "Chat Member Count"
__description__ = "Shows how many members are in the current chat. Type .members in any chat to get the count."
__author__ = "ogr42"
__version__ = "1.0.0"
__min_version__ = "11.9.0"

import traceback
from typing import Any

from org.telegram.messenger import ChatObject, UserConfig
from org.telegram.tgnet import TLRPC

from base_plugin import BasePlugin, HookResult, HookStrategy
from client_utils import (
    RequestCallback,
    get_messages_controller,
    send_message,
    send_request,
)
from android_utils import log
from ui.bulletin import BulletinHelper
from ui.settings import Divider, Header, Input, Switch

DEFAULT_COMMAND = ".members"


def _format_count(count: int) -> str:
    return f"{count:,}".replace(",", " ")


class ChatMemberCountPlugin(BasePlugin):
    def on_plugin_load(self):
        self.add_on_send_message_hook()
        log("[ChatMemberCount] plugin loaded")

    def create_settings(self):
        return [
            Header(text="Chat Member Count"),
            Input(
                key="command",
                text="Trigger command",
                default=DEFAULT_COMMAND,
                subtext="Send this text in any chat to get its member count.",
            ),
            Switch(
                key="send_as_message",
                text="Send result to chat",
                subtext="When enabled, the count is sent as a visible message. "
                        "When disabled, it is shown only to you as a notification.",
                default=False,
            ),
            Divider(
                text="Works in groups, supergroups and channels. "
                     "The command itself is never sent to the chat."
            ),
        ]

    def _command(self) -> str:
        command = self.get_setting("command", DEFAULT_COMMAND)
        if not isinstance(command, str) or not command.strip():
            return DEFAULT_COMMAND
        return command.strip()

    def on_send_message_hook(self, account: int, params: Any) -> HookResult:
        try:
            message = getattr(params, "message", None)
            if not isinstance(message, str):
                return HookResult()
            if message.strip().lower() != self._command().lower():
                return HookResult()

            self._report_member_count(account, params.peer)
            return HookResult(strategy=HookStrategy.CANCEL)
        except Exception:
            log(f"[ChatMemberCount] hook error: {traceback.format_exc()}")
            return HookResult()

    def _report_member_count(self, account: int, dialog_id: int):
        if dialog_id >= 0:
            self._report_private_chat(account, dialog_id)
            return

        chat_id = -dialog_id
        controller = get_messages_controller()
        chat = controller.getChat(chat_id)
        if chat is None:
            BulletinHelper.show_error("Could not resolve this chat.")
            return

        if ChatObject.isChannel(chat):
            self._request_channel_count(controller, chat, chat_id, dialog_id)
        else:
            self._request_basic_group_count(chat, chat_id, dialog_id)

    def _report_private_chat(self, account: int, dialog_id: int):
        if dialog_id == UserConfig.getInstance(account).getClientUserId():
            self._deliver(dialog_id, "☁️ Saved Messages — it's just you here.")
            return

        user = get_messages_controller().getUser(dialog_id)
        name = user.first_name if user and user.first_name else "this user"
        if user and user.bot:
            self._deliver(dialog_id, f"🤖 Chat with bot {name} — 2 participants.")
        else:
            self._deliver(dialog_id, f"👤 Private chat with {name} — 2 participants.")

    def _request_channel_count(self, controller, chat, chat_id: int, dialog_id: int):
        title = chat.title or "This chat"
        is_broadcast = not chat.megagroup
        cached_count = chat.participants_count or 0

        def handle_response(response, error):
            try:
                if error is not None or response is None:
                    if cached_count > 0:
                        self._deliver_chat_count(dialog_id, title, cached_count, is_broadcast)
                    else:
                        reason = error.text if error is not None else "no response"
                        BulletinHelper.show_error(f"Failed to get member count: {reason}")
                    return
                count = response.full_chat.participants_count
                self._deliver_chat_count(dialog_id, title, count, is_broadcast)
            except Exception:
                log(f"[ChatMemberCount] channel response error: {traceback.format_exc()}")

        req = TLRPC.TL_channels_getFullChannel()
        req.channel = controller.getInputChannel(chat_id)
        send_request(req, RequestCallback(handle_response))

    def _request_basic_group_count(self, chat, chat_id: int, dialog_id: int):
        title = chat.title or "This chat"
        cached_count = chat.participants_count or 0

        def handle_response(response, error):
            try:
                if error is not None or response is None:
                    if cached_count > 0:
                        self._deliver_chat_count(dialog_id, title, cached_count, False)
                    else:
                        reason = error.text if error is not None else "no response"
                        BulletinHelper.show_error(f"Failed to get member count: {reason}")
                    return

                participants = getattr(response.full_chat, "participants", None)
                members = getattr(participants, "participants", None) if participants else None
                if members is not None:
                    self._deliver_chat_count(dialog_id, title, members.size(), False)
                elif cached_count > 0:
                    self._deliver_chat_count(dialog_id, title, cached_count, False)
                else:
                    BulletinHelper.show_error("Member list is not available for this group.")
            except Exception:
                log(f"[ChatMemberCount] group response error: {traceback.format_exc()}")

        req = TLRPC.TL_messages_getFullChat()
        req.chat_id = chat_id
        send_request(req, RequestCallback(handle_response))

    def _deliver_chat_count(self, dialog_id: int, title: str, count: int, is_broadcast: bool):
        noun = "subscriber" if is_broadcast else "member"
        plural = noun if count == 1 else noun + "s"
        icon = "📣" if is_broadcast else "👥"
        self._deliver(dialog_id, f"{icon} {title} — {_format_count(count)} {plural}.")

    def _deliver(self, dialog_id: int, text: str):
        if self.get_setting("send_as_message", False):
            send_message({"peer": dialog_id, "message": text})
        else:
            BulletinHelper.show_info(text)

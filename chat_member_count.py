__id__ = "chat_member_count"
__name__ = "Chat Member Count"
__description__ = "Shows how many members are in the current chat. Type .members in any chat to get the count."
__author__ = "ogr42"
__version__ = "1.1.0"
__min_version__ = "11.9.0"

import traceback
from typing import Any

from org.telegram.messenger import ChatObject, DialogObject, UserConfig
from org.telegram.tgnet import TLRPC

from base_plugin import BasePlugin, HookResult, HookStrategy
from client_utils import (
    RequestCallback,
    get_messages_controller,
    send_message,
    send_request,
)
from android_utils import log, run_on_ui_thread
from ui.bulletin import BulletinHelper
from ui.settings import Divider, Header, Input, Switch

DEFAULT_COMMAND = ".members"
COMMAND_PREFIXES = ".!/"

# SendMessageParams fields that indicate the message carries an attachment;
# such sends must never be swallowed by the trigger command.
ATTACHMENT_FIELDS = (
    "photo",
    "document",
    "videoEditedInfo",
    "location",
    "poll",
    "game",
    "invoice",
    "user",
)


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
                subtext="Send this text in any chat to get its member count. "
                        "Must start with '.', '!' or '/' so ordinary messages "
                        "are never intercepted.",
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
        if not isinstance(command, str):
            return DEFAULT_COMMAND
        command = command.strip()
        # A trigger without a command prefix (or containing spaces) could
        # swallow ordinary messages, so fall back to the default instead.
        if len(command) < 2 or command[0] not in COMMAND_PREFIXES or " " in command:
            return DEFAULT_COMMAND
        return command

    @staticmethod
    def _has_attachment(params: Any) -> bool:
        return any(
            getattr(params, field, None) is not None for field in ATTACHMENT_FIELDS
        )

    def on_send_message_hook(self, account: int, params: Any) -> HookResult:
        try:
            message = getattr(params, "message", None)
            if not isinstance(message, str):
                return HookResult()
            if message.strip().lower() != self._command().lower():
                return HookResult()
            # A media send whose caption matches the trigger must go through
            # untouched — cancelling it would drop the attachment.
            if self._has_attachment(params):
                return HookResult()

            self._report_member_count(account, params.peer)
            return HookResult(strategy=HookStrategy.CANCEL)
        except Exception:
            log(f"[ChatMemberCount] hook error: {traceback.format_exc()}")
            return HookResult()

    def _report_member_count(self, account: int, dialog_id: int):
        if DialogObject.isEncryptedDialog(dialog_id):
            self._report_secret_chat(dialog_id)
            return

        if dialog_id >= 0:
            self._report_private_chat(account, dialog_id)
            return

        chat_id = -dialog_id
        controller = get_messages_controller()
        chat = controller.getChat(chat_id)
        if chat is None:
            self._show_error("Could not resolve this chat.")
            return

        if ChatObject.isChannel(chat):
            self._request_channel_count(controller, chat, chat_id, dialog_id)
        else:
            self._request_basic_group_count(chat, chat_id, dialog_id)

    def _report_secret_chat(self, dialog_id: int):
        controller = get_messages_controller()
        encrypted_chat = controller.getEncryptedChat(
            DialogObject.getEncryptedChatId(dialog_id)
        )
        user = (
            controller.getUser(encrypted_chat.user_id)
            if encrypted_chat is not None
            else None
        )
        name = user.first_name if user and user.first_name else "this user"
        self._deliver(dialog_id, f"🔒 Secret chat with {name} — 2 participants.")

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
        # Gigagroups (broadcast groups) have megagroup == False but are still
        # groups, so their participants are "members", not "subscribers".
        is_broadcast = not (chat.megagroup or chat.gigagroup)
        cached_count = chat.participants_count or 0

        def handle_response(response, error):
            try:
                if error is not None or response is None:
                    if cached_count > 0:
                        self._deliver_chat_count(
                            dialog_id, title, cached_count, is_broadcast, cached=True
                        )
                    else:
                        reason = error.text if error is not None else "no response"
                        self._show_error(f"Failed to get member count: {reason}")
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
                        self._deliver_chat_count(
                            dialog_id, title, cached_count, False, cached=True
                        )
                    else:
                        reason = error.text if error is not None else "no response"
                        self._show_error(f"Failed to get member count: {reason}")
                    return

                participants = getattr(response.full_chat, "participants", None)
                members = getattr(participants, "participants", None) if participants else None
                if members is not None:
                    self._deliver_chat_count(dialog_id, title, members.size(), False)
                elif cached_count > 0:
                    self._deliver_chat_count(
                        dialog_id, title, cached_count, False, cached=True
                    )
                else:
                    self._show_error("Member list is not available for this group.")
            except Exception:
                log(f"[ChatMemberCount] group response error: {traceback.format_exc()}")

        req = TLRPC.TL_messages_getFullChat()
        req.chat_id = chat_id
        send_request(req, RequestCallback(handle_response))

    def _deliver_chat_count(
        self,
        dialog_id: int,
        title: str,
        count: int,
        is_broadcast: bool,
        cached: bool = False,
    ):
        noun = "subscriber" if is_broadcast else "member"
        plural = noun if count == 1 else noun + "s"
        icon = "📣" if is_broadcast else "👥"
        suffix = " (cached)" if cached else ""
        self._deliver(dialog_id, f"{icon} {title} — {_format_count(count)} {plural}{suffix}.")

    # RPC callbacks arrive on the network thread; bulletins and message
    # sending must run on the UI thread.
    def _deliver(self, dialog_id: int, text: str):
        if self.get_setting("send_as_message", False):
            run_on_ui_thread(lambda: send_message({"peer": dialog_id, "message": text}))
        else:
            run_on_ui_thread(lambda: BulletinHelper.show_info(text))

    @staticmethod
    def _show_error(text: str):
        run_on_ui_thread(lambda: BulletinHelper.show_error(text))

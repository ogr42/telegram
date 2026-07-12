# Chat Member Count — exteraGram plugin

A Python plugin for [exteraGram](https://github.com/exteraSquad/exteraGram) (the third-party
Telegram client by exteraSquad) that shows how many members are in the current chat.

## What it does

Type the trigger command (default: `.members`) in any chat and send it. The plugin
intercepts the message before it is sent — nothing is posted to the chat — and fetches
the up-to-date participant count from the Telegram API:

| Chat type | Result |
|---|---|
| Supergroup | `👥 Title — 1 234 members` (via `channels.getFullChannel`) |
| Broadcast channel | `📣 Title — 56 789 subscribers` (via `channels.getFullChannel`) |
| Basic group | `👥 Title — 12 members` (via `messages.getFullChat`) |
| Private chat / bot | `👤 Private chat with Name — 2 participants` |
| Secret chat | `🔒 Secret chat with Name — 2 participants` |
| Saved Messages | `☁️ Saved Messages — it's just you here.` |

If the API request fails but a locally cached count is available, the cached value is
shown with a `(cached)` suffix.

By default the result is shown only to you as an in-app bulletin notification.
An optional setting sends it to the chat as a visible message instead.

## Settings

Open **exteraGram Settings → Plugins → Chat Member Count**:

- **Trigger command** — the text that activates the plugin (default `.members`).
  It must start with `.`, `!` or `/` and contain no spaces, so ordinary messages
  can never be intercepted; invalid values fall back to the default.
- **Send result to chat** — off by default; when enabled, the count is sent as a
  regular message to the chat instead of a private notification.

## Installation

1. Install exteraGram 11.9.0 or newer.
2. Download [`chat_member_count.py`](chat_member_count.py) to your device
   (you may rename it to `chat_member_count.plugin` — both extensions work).
3. In exteraGram open **Settings → Plugins → Load plugin from file** and pick the file,
   or simply send the file to yourself in Telegram, tap it, and choose to install it
   as a plugin.
4. Enable the plugin, open any chat and send `.members`.

## How it works

exteraGram embeds a Python runtime (Chaquopy) and exposes a plugin SDK:

- The plugin declares metadata via module-level fields (`__id__`, `__name__`,
  `__version__`, `__min_version__`, …) and a class extending `BasePlugin`.
- `on_plugin_load` registers an outgoing-message hook with `add_on_send_message_hook()`.
- `on_send_message_hook` checks whether the typed text matches the trigger command.
  If so, it returns `HookResult(strategy=HookStrategy.CANCEL)` so the command text is
  never actually sent, and kicks off the lookup.
- The lookup resolves the dialog through `client_utils.get_messages_controller()` and
  sends a raw MTProto request (`TLRPC.TL_channels_getFullChannel` or
  `TLRPC.TL_messages_getFullChat`) via `client_utils.send_request`, falling back to the
  locally cached `participants_count` if the request fails.
- The result is displayed with `ui.bulletin.BulletinHelper` or sent with
  `client_utils.send_message`, depending on the setting.

Plugin SDK documentation: https://plugins.exteragram.app/docs

---
name: Telegram message typography
description: Platform constraint for matching Telegram bot screenshots
---

Telegram bot messages cannot force an arbitrary font file or client font. The practical match is the message text, casing, supported bold/italic formatting, emojis, line breaks, and inline keyboard layout.

**Why:** Telegram renders the final message inside the user's Telegram client, whose font and accessibility settings are outside the bot's control.

**How to apply:** When matching a Telegram screenshot, reproduce the copy and supported formatting closely, but explain that pixel-identical font rendering requires matching the Telegram client's own font settings.
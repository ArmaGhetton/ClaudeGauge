## ClaudeGauge — Claude usage gauge for Windows 11

*[Читать по-русски](Readme.md)*

Shows on your desktop how much of your Claude limits you've used and when they reset.

- **Session · 5 hours** — percentage and exact time until reset
- **Week · all models** — weekly limit, reset date and time
- **Week · Sonnet** and **Week · Opus** — separate weekly limits
- **Extra usage** — if extra usage is enabled on your account

Visually it's a dark or light card with rounded corners in the Windows 11 style, no window frame, draggable with the mouse.

---

## Installation

### Step 1. Python

The widget needs Python (everything it uses is already in the standard library, no `pip install` required).

Check whether it's installed: press `Win + R`, type `cmd`, and in the window that opens type

```
python --version
```

If you see a version number (3.9 or newer) — go to step 2.

If it says the command isn't found — download Python from https://www.python.org/downloads/
During installation **make sure to check "Add python.exe to PATH"** on the first screen.

### Step 2. Put the files in a folder

Create a folder, for example `C:\ClaudeWidget`, and put these files in it:

- `ClaudeGauge.pyw`
- `ClaudeGauge.bat`
- `ClaudeGauge.ico`

All three files must be next to each other. Without `ClaudeGauge.ico` the widget still works, just without an icon.

### Step 3. Sign in to your Claude account

The widget gets its data from the same place as the `/usage` command in Claude Code. For it to see your account, you need to sign in to Claude Code once:

```
npm install -g @anthropic-ai/claude-code
claude
```

Inside Claude Code run `/login` and sign in with your Pro or Max subscription.
After that a file `C:\Users\YourName\.claude\.credentials.json` will appear — the widget reads the token from there and refreshes it automatically afterward.

### Step 4. Launch

Double-click **`ClaudeGauge.bat`**.

Right after launching, it's worth creating a shortcut: right-click the widget → "Create desktop shortcut". A `ClaudeGauge` shortcut with a proper icon will appear, and it's more convenient to launch from there afterward — you won't need the bat file anymore. The shortcut can be pinned to the taskbar or the Start menu.

Bat files don't have their own icon: Windows draws the same generic icon for every file of that type, and you can only change it for all of them at once.

The widget will appear in the top-right corner of the screen. Drag it wherever you like with the mouse — the position is remembered.

---

## Controls

| Action | How |
|---|---|
| Move | hold the left mouse button anywhere on it and drag |
| Menu | right-click the widget |
| Settings | ⚙ icon |
| Refresh manually | ⟳ icon |
| Close | ✕ icon or the Esc key |

---

## Settings

**Appearance**
- Language — Russian or English
- Opacity — from 30% to 100%
- Widget size — from 80% to 170%
- Theme — dark, OLED (pure black), light, plus gradient "Aurora" and "Sunset"
- Accent — six colors
- Always on top
- Hide from taskbar — the widget doesn't need its own button at the bottom of the screen
- Compact mode — session and weekly limit only
- Glass effect — the card becomes a blur of the desktop behind the window, like Windows 11 flyouts. Uses an undocumented Windows API and may not work on some builds — in that case nothing changes
- Lock position — the widget stops being draggable, so you don't accidentally move it

**Data**
- Show weekly Sonnet and Opus limits
- Show extra usage
- Refresh interval — 180 seconds by default
- Warning threshold — the percentage at which the bar turns yellow (80% by default); above 95% it's always red
- Sound alert at threshold

**System**
- Launch at Windows sign-in
- Refresh access token automatically
- Custom token field — if you don't want to install Claude Code

Settings are saved to `%APPDATA%\ClaudeGauge\settings.json`.

---

## Why the interval is 180 seconds

The endpoint that returns limit data strictly rate-limits requests. With an interval under two minutes it starts responding with error 429 and the widget shows "Too many requests". 180 seconds is a proven safe value; you can't set less than 120.

The countdown to reset still runs every second — it's calculated locally and doesn't use up any requests.

---

## If something doesn't work

**"Not logged in to Claude"**
Claude Code isn't installed, or `/login` hasn't been run in it. Go through step 3. Or paste a token manually in settings.

**"Access token expired"**
Turn on "Refresh access token automatically" in settings, or just launch Claude Code — it will refresh the token itself.

**"Too many requests"**
Raise the refresh interval to 300 seconds.

**"No connection"**
Check your internet connection, VPN, or corporate proxy.

**The widget won't launch**
Run `ClaudeGauge.pyw` from the command line with `python ClaudeGauge.pyw` — you'll see the error text. Also check `%APPDATA%\ClaudeGauge\error.log`.

---

## Important note about the token

The widget reads Claude Code's `.credentials.json` and refreshes the access token when needed. Before writing to it for the first time, it makes a backup copy `.credentials.json.backup` next to the original.

If Claude Code ever asks you to sign in again after that — just run `/login` in it, nothing will be lost.

The token is never sent anywhere except Anthropic's servers. All the code is in a single file, which you can open in Notepad and read.

---

## Disclaimer

The `/api/oauth/usage` endpoint the numbers come from is not officially documented by Anthropic — it's the same source the `/usage` command in Claude Code uses, and the same one other community tools use. Anthropic can change it at any time. This is not an official Anthropic product.

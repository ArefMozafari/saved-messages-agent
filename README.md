# 📥 Saved Messages Agent

**Telegram Saved Messages → AI Categorizer → Notion**

An intelligent agent that watches your Telegram Saved Messages, classifies each message using Google Gemini AI, lets you pick categories via inline buttons, and saves everything to organized Notion databases.

## Architecture

```
Telegram Saved Messages
        │
        ▼
  Pyrogram Userbot ──────► Gemini AI Classifier
        │                        │
        │                ┌───────┘
        │                ▼
        │         Category Suggestions
        │                │
        ▼                ▼
  Telegram Bot ◄──── Inline Keyboard
        │            (you pick categories)
        │
        ▼
  Notion API ── creates pages in category databases
```

## Categories

| Emoji | Category | Examples |
|-------|----------|----------|
| 🛒 | Wishlist | Product links, screenshots of items to buy |
| 📺 | Watch Later | Movie / series names, YouTube / reel links |
| 📚 | Read Later | Book names, article links, blog posts |
| 🎓 | Educational | Tutorial links, educational reels, courses |
| 🔐 | Credentials | Passwords, API keys, login info |
| 💡 | Ideas | Thoughts, ideas to explore later |
| 🎵 | Music / Practice | Singing practices, music files |
| 🔗 | Useful Links | General helpful links to save |
| 📝 | Notes | Quick notes, reminders |
| 📎 | Other | Anything else |

## Setup

### 1. Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.11+ (uv will manage this for you)
- A Telegram account
- A Google Gemini API key
- A Notion account with an integration

### 2. Telegram credentials

**Userbot (to read Saved Messages):**
1. Go to [my.telegram.org](https://my.telegram.org)
2. Log in → API development tools
3. Create an application → note your `API_ID` and `API_HASH`

**Bot (to send you category buttons):**
1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` and follow the prompts
3. Copy the bot token
4. **Important:** Start a conversation with your new bot (send `/start`) so it can message you

### 3. Google Gemini API key

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Create an API key

### 4. Notion integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new integration → copy the token
3. Create a new page in Notion (this will be the parent for all category databases)
4. Share that page with your integration (click ··· → Add connections → select your integration)
5. Copy the page ID from the URL (`https://notion.so/Your-Page-<PAGE_ID>`)

### 5. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 6. Install & run

```bash
uv sync
uv run python run.py
```

On first run, Pyrogram will ask for your phone number and OTP code in the terminal. After that, a session file is created and subsequent starts are automatic.

### Alternative: Docker

```bash
docker compose up -d
# First run: check logs for the phone login prompt
docker compose logs -f agent
```

## Usage

1. **Save a message** in Telegram — forward something, paste a link, drop a screenshot, type a note, etc.
2. **Open your bot chat** — you'll see a message with AI's summary and category buttons
3. **Tap categories** — selected ones show ✅
4. **Tap Confirm** — the item is saved to the matching Notion database(s)

## Bot commands

- `/start` — welcome message
- `/categories` — list all available categories

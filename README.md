# Usher — Clash of Clans Discord War Bot

A self-hostable Discord bot that monitors your Clash of Clans clan's wars and sends attack reminders, war result summaries, and capital raid summaries to your Discord server.

## Features

- **War attack reminders** — pings members who still have attacks at configurable time thresholds (e.g. 12h, 3h, 1h before war end)
- **War result summaries** — posts win/loss/tie summary with stars, destruction, and missed attacks
- **Capital raid summaries** — posts total gold looted and participant breakdown after raid weekend
- **Account linking** — link Discord users to CoC player tags for `@mention` reminders
- **Prefix commands** — all config and user interaction via Discord text commands

## Prerequisites

- A **Discord bot token** — see [Discord Developer Portal](https://discord.com/developers/applications)
- A **Clash of Clans API key** — see [CoC Developer Portal](https://developer.clashofclans.com)
- **Docker** installed on your server
- Your server's **public IP** whitelisted in the CoC API key settings

---

## Quick Start (Local / Docker)

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd usher
```

### 2. Create your environment file

```bash
cp .env.example .env
# Edit .env and fill in DISCORD_TOKEN and COC_API_TOKEN
```

### 3. Build and run with Docker Compose

```bash
docker compose up --build -d
```

The SQLite database is stored in a Docker volume (`coc-bot-data`) and persists across restarts.

### 4. Configure the bot in Discord

In your Discord server (you must have **Manage Server** permission):

```
!setclan #YOURCLANTAG
!setwarchannel #war-reminders
!setresultschannel #war-results
!setreminders 12h 3h 1h
```

---

## Commands

### Admin commands (require Manage Server)

| Command | Description |
|---|---|
| `!setclan #TAG` | Set the clan to monitor |
| `!setwarchannel #channel` | Set channel for war attack reminders |
| `!setresultschannel #channel` | Set channel for war result summaries |
| `!setcapitalchannel #channel` | Set channel for capital raid summaries |
| `!setreminders 12h 3h 1h` | Set reminder time thresholds |
| `!status` | Show current config and war state |
| `!testreminder` | Preview a reminder message (no pings) |

### User commands

| Command | Description |
|---|---|
| `!war` | Show current war status and remaining attacks |
| `!link #TAG [nickname]` | Link your Discord to a CoC player tag |
| `!unlink #TAG` | Remove a linked tag |
| `!unlinkall` | Remove all your linked tags |
| `!links` | List your linked tags |

---

## Deploying to AWS EC2

### 1. Launch an EC2 instance

- Use a **t3.micro** (free tier eligible) with Amazon Linux 2 or Ubuntu
- Attach an **Elastic IP** to the instance

### 2. Whitelist the Elastic IP in CoC API

- Go to [developer.clashofclans.com](https://developer.clashofclans.com)
- Edit your API key and add the Elastic IP to the allowed IP list

### 3. Install Docker

```bash
sudo yum update -y          # or apt-get update
sudo yum install -y docker  # or apt-get install docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
```

### 4. Copy files and configure

```bash
mkdir ~/coc-bot && cd ~/coc-bot
# Copy your project files here (scp, git clone, etc.)
cp .env.example coc-bot.env
# Edit coc-bot.env with your tokens
```

### 5. Build the image

```bash
docker build -t coc-bot:latest .
docker volume create coc-bot-data
```

### 6. Set up systemd for automatic start/restart

```bash
sudo cp deploy/coc-bot.service /etc/systemd/system/coc-bot.service
# Edit the service file to confirm env-file path is correct
sudo systemctl daemon-reload
sudo systemctl enable --now coc-bot.service
```

Check status:
```bash
sudo systemctl status coc-bot.service
docker logs coc-bot.service
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | Yes | — | Discord bot token |
| `COC_API_TOKEN` | Yes | — | Clash of Clans API key |
| `COMMAND_PREFIX` | No | `!` | Bot command prefix |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `SQLITE_PATH` | No | `/app/data/bot.db` | Path to SQLite database inside container |
| `POLL_INTERVAL` | No | `120` | CoC API poll interval in seconds |

---

## Data Model

The bot uses a SQLite database with the following tables:

- **`guild_config`** — Per-server configuration (clan tag, channels, reminder thresholds)
- **`user_links`** — Discord user ↔ CoC player tag mappings
- **`wars`** — War records with state and summary status
- **`reminders_sent`** — Deduplication log for sent reminders
- **`capital_seasons_posted`** — Deduplication log for capital raid summaries

---

## License

MIT

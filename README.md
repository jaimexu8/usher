# Usher: Clash of Clans Discord War Bot

A self-hostable Discord bot that monitors your Clash of Clans clan's wars and sends attack reminders, war result summaries, and capital raid summaries to your Discord server.

## Features

- **War attack reminders**: pings members who still have attacks at configurable time thresholds (e.g. 12h, 3h, 1h before war end)
- **War result summaries**: posts win/loss/tie summary with stars, destruction, and missed attacks
- **Capital raid summaries**: posts total gold looted and participant breakdown after raid weekend
- **Account linking**: link Discord users to CoC player tags for `@mention` reminders
- **Prefix commands**: all config and user interaction via Discord text commands

## Prerequisites

- A **Discord bot token**: see [Discord Developer Portal](https://discord.com/developers/applications)
- A **Clash of Clans API key**: see [CoC Developer Portal](https://developer.clashofclans.com)
- **Docker** installed on your server
- Your server's **public IP** whitelisted in the CoC API key settings

---

## Quick Start (Local / Docker)

### 1. Clone the repository

```bash
git clone https://github.com/jaimexu8/usher
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

| Command                       | Description                            |
| ----------------------------- | -------------------------------------- |
| `!setclan #TAG`               | Set the clan to monitor                |
| `!setwarchannel #channel`     | Set channel for war attack reminders   |
| `!setresultschannel #channel` | Set channel for war result summaries   |
| `!setcapitalchannel #channel` | Set channel for capital raid summaries |
| `!setreminders 12h 3h 1h`     | Set reminder time thresholds           |
| `!status`                     | Show current config and war state      |
| `!testreminder`               | Preview a reminder message (no pings)  |

### User commands

| Command | Description |
| ------- | ----------- |
| `!war` | Show current war status and remaining attacks |
| `!link #TAG [nickname]` | Link your Discord to a CoC player tag |
| `!link @user #TAG [nickname]` | *(Admin/Usher Handler)* Link another user to a CoC tag (use @mention or Discord user ID) |
| `!unlink #TAG` | Remove a linked tag from your account |
| `!unlink @user #TAG` | *(Admin/Usher Handler)* Remove a linked tag from another user's account |
| `!unlinkall` | Remove all your linked tags |
| `!unlinkall @user` | *(Admin/Usher Handler)* Remove all linked tags for another user |
| `!links` | List your linked CoC accounts |
| `!links @user` | *(Admin/Usher Handler)* List another user's linked CoC accounts |

**Linking as another user:** Server admins (Manage Server) and members with the **Usher Handler** role can run `!link`, `!unlink`, `!unlinkall`, and `!links` for someone else by passing that user as the first argument—either **@mention** (e.g. `@username`) or their **Discord user ID** (e.g. `123456789012345678`).

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
sudo journalctl -u coc-bot.service -n 50
```

---

## Development

Develop and test locally, then deploy updates to EC2 by pulling and rebuilding on the instance.

### Local

Run the bot locally for testing.

```bash
docker compose up --build
```

### EC2

1. SSH into the instance and go to the repo directory (where the Dockerfile lives):

```bash
 ssh -i your-key.pem ec2-user@<ELASTIC_IP>
 cd ~/coc-bot
```

2. Run the deploy script (pulls latest code, rebuilds image, restarts the service):

```bash
 chmod +x deploy/update.sh   # only needed once
 ./deploy/update.sh          # deploy from main
 ./deploy/update.sh feature/my-branch   # deploy from a specific branch
```

The script will:

- `git fetch origin` then `git checkout <branch>` and `git pull origin <branch>` (default branch: `main`)
- `sudo docker build -t coc-bot:latest .`
- `sudo systemctl restart coc-bot.service`
- Print service status

3. Watch logs if needed:

```bash
 sudo journalctl -u coc-bot.service -f
```

---

## Environment Variables

| Variable         | Required | Default            | Description                              |
| ---------------- | -------- | ------------------ | ---------------------------------------- |
| `DISCORD_TOKEN`  | Yes      | —                  | Discord bot token                        |
| `COC_API_TOKEN`  | Yes      | —                  | Clash of Clans API key                   |
| `COMMAND_PREFIX` | No       | `!`                | Bot command prefix                       |
| `LOG_LEVEL`      | No       | `INFO`             | Logging level (DEBUG/INFO/WARNING/ERROR) |
| `SQLITE_PATH`    | No       | `/app/data/bot.db` | Path to SQLite database inside container |
| `POLL_INTERVAL`  | No       | `120`              | CoC API poll interval in seconds         |

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

## Project PRD – Clash of Clans Discord War Bot

### 1. Overview

**Goal**: Build a self-hostable, open-source Discord bot (Python) that uses the official Clash of Clans (CoC) API to:
- Monitor a **single clan’s** wars and clan capital activity.
- Send **war attack reminders** to a configured Discord text channel at configurable time offsets before war end.
- Post **informational summaries** (war results, capital raid outcomes) to designated Discord channels.

**Deployment**:
- Language: **Python 3.x**
- Data: **SQLite** file on disk (Docker volume)
- Hosting: **AWS EC2** (within free tier) with **Elastic IP** whitelisted in CoC dev portal.
- Packaging: **Dockerized** bot, orchestrated by **systemd** on EC2 with automatic restart on crash/reboot.

**Target audience**:
- Primary: The author’s private clan Discord server.
- Secondary: Other technically inclined clan leaders who can clone the repo, configure keys, and deploy on their own infrastructure.

### 2. Constraints and Non-Goals

- **Single clan per deployment**: One monitored clan per running bot instance (per Discord guild). Multi-clan support is out-of-scope for v1.
- **Single Discord server focus**: Data model should support multi-guild, but v1 UX assumes one guild; no multi-tenant shared hosting.
- **No web UI**: All configuration and interactions are via Discord prefix commands and environment variables.
- **No external DB**: Do **not** introduce Postgres, MySQL, or managed DBs. Use file-backed SQLite only.
- **No public “app” distribution**: Bot is designed for self-hosters, not as a hosted SaaS. No OAuth2 “install to multiple servers” flow beyond standard Discord bot invite.

### 3. High-Level Architecture

- **Discord Layer**:
  - Library: `discord.py` (or equivalent modern fork) using prefix commands (e.g., `!setclan`, `!setwarchannel`).
  - Single bot process, one shard, no horizontal scaling.

- **Clash of Clans Integration**:
  - Use official CoC Developer API with `Authorization: Bearer <COC_API_TOKEN>` header.
  - CoC API key IP-restricted to the EC2 instance’s Elastic IP.
  - Endpoints (non-exhaustive):
    - Current war: `/clans/{clanTag}/currentwar`
    - (Optional later) War log, capital raid seasons, player info.

- **Scheduling / Polling**:
  - Long-running loop that polls CoC at a fixed interval (e.g., 60–180 seconds).
  - On each poll:
    - Refresh current war state and capital state for configured clan.
    - Compute remaining time to war end, remaining attacks per player.
    - Trigger reminder or summary logic based on time thresholds and prior state persisted in SQLite.

- **Storage**:
  - SQLite DB persisted on disk **inside a Docker volume** (e.g., `coc-bot-data`).
  - No in-memory-only DB; data must survive process and container restarts.

- **Deployment / Ops**:
  - Docker image built from a `Dockerfile` (Python base image, slim variant).
  - On EC2: Docker installed and enabled; bot container managed by a **systemd service** with `Restart=always`.
  - Elastic IP attached to EC2 instance; that IP whitelisted in CoC dev portal.

### 4. Core Features and Requirements

#### 4.1 War Monitoring and Reminders

**User Story**: As a clan leader, I want the bot to remind members who still have war attacks left at specific times before war end, so we don’t miss attacks.

**War Scope**:
- v1: Support **regular clan wars** and **CWL** if possible via the same current war endpoint. Friendly wars are lower priority but should not break the bot (can be ignored or treated as regular).

**Configuration**:
- Exactly **one clan** is monitored, configured via a prefix command:
  - `!setclan #CLANTAG`
- Reminder target channel:
  - `!setwarchannel #channel`
- Time thresholds (minutes or human-readable like `12h`, `3h`, `1h`):
  - `!setreminders 12h 3h 1h` (stored as minutes in DB for internal use).

**Behavior**:
- Bot periodically polls CoC current war endpoint.
- When there is **no active war**:
  - Bot does nothing beyond possibly indicating “no war” to manual commands.
- During **preparation**:
  - No reminders yet; only optional status output via commands.
- During **active war**:
  - For each configured threshold (e.g., 12h, 3h, 1h before end-time):
    - When `time_until_end` crosses below the threshold for the first time:
      - Determine set of members with at least one attack remaining.
      - For each player with remaining attacks:
        - If linked to a Discord user: include an `@mention`.
        - If **not linked**: include CoC in-game name and/or tag as plain text, **no ping**.
      - Post a single message in the reminders channel summarizing all players with remaining attacks.
      - Persist that this (war, threshold, player) reminder has been sent to avoid duplicates.

**Reminder De-duplication**:
- Define a `war_id` from CoC war metadata (e.g., clanTag + preparationStartTime + endTime).
- Keep a `reminders_sent` table with:
  - `war_id`, `threshold_minutes`, `player_tag`, `sent_at`.
- When constructing a reminder, only include players who **haven’t** had a reminder sent at that threshold for that war.
- Each threshold triggers at most once per war; each player is reminded at most once per threshold.

**Reminder Message Format (example)**:

```text
⏰ **War reminder — 3 hours left**

The following players still have attacks remaining:

@Alice (MainAccount #ABC123)
@Bob (AltAccount #DEF456)
ChiefName (#GHI789)
```

#### 4.2 War End Summaries

**User Story**: As a clan leader, I want automatic war result posts so everyone can see outcome and performance without manually checking the game.

**Configuration**:
- A channel for war results:
  - `!setresultschannel #channel` (can default to same as war channel if not configured).

**Behavior**:
- Detect transition from **active war** to “war ended” state by polling.
- Once the war is ended and not yet summarized:
  - Post a summary including:
    - Win/loss/tie.
    - Stars and destruction for both clans.
    - Missed attacks (players with remaining attacks at war end).
    - (Optional v1.1+) Top performers by stars/damage.
- Persist `war_id` as “summarized” to avoid double posts.

#### 4.3 Clan Capital Summaries (v1 scope, simple)

**User Story**: As a clan leader, I want a periodic overview of capital raid performance.

**Configuration**:
- Channel (can reuse war results channel or have its own):
  - `!setcapitalchannel #channel` (optional; if unset, use results channel).

**Behavior (simple v1)**:
- On a schedule (e.g., once after raid weekend ends) or when capital API indicates a raid season has ended:
  - Fetch last raid season results.
  - Post total capital gold looted, total upgrades, and basic participation list.
- Start with minimal information and expand over time.

### 5. Account Linking and Mentions

**User Story**: As a player, I want the bot to ping my Discord account when I have attacks left, based on my CoC account.

**Linking Rules**:
- Anyone can link; no requirement that the player is currently in the monitored clan.
- One Discord user can link **multiple** CoC player tags (main + alts).
- Per guild, a given `player_tag` is linked to at most one Discord user (new link can overwrite old by default).

**Commands**:
- `!link #PLAYERTAG [nickname]`
  - Links the caller’s Discord user to the given tag, with an optional nickname for display.
- `!unlink #PLAYERTAG`
  - Removes one linked tag for the caller.
- `!unlinkall`
  - Removes all tags for the caller (within this guild).
- `!links`
  - Lists the caller’s currently linked tags and nicknames.

**Link Validation**:
- v1: Bot **may** optionally verify that `#PLAYERTAG` is a valid CoC player by querying CoC API, but does **not** enforce clan membership.

**Reminder Mentions**:
- If player tag has a linked Discord user in DB:
  - Bot uses `@mention` of that user in reminder messages.
- If no linked user:
  - Bot shows plain text `Name (#TAG)` with **no mention**.

### 6. Commands and Permissions

**Prefix**:
- Configurable via environment variable `COMMAND_PREFIX`, default `!`.

**Admin-only commands** (require MANAGE_GUILD or a similar server admin permission):
- `!setclan #CLANTAG`
- `!setwarchannel #channel`
- `!setresultschannel #channel`
- `!setcapitalchannel #channel`
- `!setreminders 12h 3h 1h`
- `!status` (show config + last poll time + current war state)
- `!testreminder` (simulate a reminder without posting pings, for formatting/testing)

**User commands**:
- `!link`, `!unlink`, `!unlinkall`, `!links`
- `!war` (manual snapshot of current war: time left, who has attacks left, but no pings)

### 7. Data Model (SQLite)

Use a single SQLite DB file (e.g., `/app/data/bot.db`) persisted via Docker volume.

#### 7.1 Tables (initial design)

- `guild_config`
  - `guild_id` (PK; Discord guild ID)
  - `clan_tag` (string, required)
  - `war_channel_id` (nullable)
  - `results_channel_id` (nullable)
  - `capital_channel_id` (nullable)
  - `reminder_thresholds` (string, e.g. JSON array of minutes `[720, 180, 60]`)
  - `timezone` (string; optional; default UTC)
  - `created_at`, `updated_at`

- `user_links`
  - `id` (PK)
  - `guild_id`
  - `discord_user_id`
  - `player_tag`
  - `nickname` (optional display name, e.g. “Main”, “Alt”)
  - `created_at`
  - **Unique constraint**: `(guild_id, player_tag)` to ensure one user per tag per guild.

- `wars`
  - `id` (PK)
  - `guild_id`
  - `war_id` (string; derived composite ID)
  - `state` (enum-like: PREP, IN_WAR, ENDED)
  - `end_time` (timestamp)
  - `summary_posted` (bool)
  - `created_at`, `updated_at`
  - **Unique constraint**: `(guild_id, war_id)`

- `reminders_sent`
  - `id` (PK)
  - `guild_id`
  - `war_id`
  - `player_tag`
  - `threshold_minutes`
  - `sent_at`
  - **Unique constraint**: `(guild_id, war_id, player_tag, threshold_minutes)`

This schema is intentionally simple but covers the key needs; it can be extended without breaking existing deployments.

### 8. Polling and Reminder Algorithm

**Polling Loop** (single task, no external scheduler):
1. Sleep for a fixed interval (e.g., 60–180 seconds).
2. For each configured guild (v1 likely only one):
   1. Read `clan_tag` from `guild_config`.
   2. Call CoC current war endpoint for that clan.
   3. If no war:
      - Mark any existing `wars` rows for this guild as ended if appropriate.
      - Continue.
   4. Compute or lookup `war_id` from CoC response.
   5. Upsert `wars` row (state, end_time).
   6. If war is in **IN_WAR** state:
      - Compute `time_until_end` in minutes.
      - For each `threshold` in `reminder_thresholds`:
        - If `time_until_end <= threshold` and there is **no** `reminders_sent` row for `(guild_id, war_id, threshold)` for a given player with remaining attacks:
          - Build reminder message for those players.
          - Post reminder to `war_channel_id`.
          - Insert `reminders_sent` rows for each mentioned player at that threshold.
   7. If war transitioned to **ENDED** and `summary_posted` is False:
      - Build summary message.
      - Post to `results_channel_id` (or fallback).
      - Set `summary_posted = True`.

**Failure handling**:
- CoC API failures: log, back off, and retry on next loop iteration. Do not crash the bot.
- Discord errors (e.g., missing permissions): log clearly, but do not exit the process.

### 9. Deployment and Operations

#### 9.1 Configuration via Environment Variables

- `DISCORD_TOKEN` – Discord bot token (required).
- `COC_API_TOKEN` – Clash of Clans Developer API key (required).
- `COMMAND_PREFIX` – Bot prefix, default `"!"`.
- `LOG_LEVEL` – e.g., `INFO` or `DEBUG`.
- `SQLITE_PATH` – path to DB file inside container (default `/app/data/bot.db`).

These should be passed into the container via `--env-file` or environment entries in the systemd unit.

#### 9.2 Dockerization

**Requirements for Dockerfile**:
- Use an official Python base image (e.g., `python:3.x-slim`).
- Install system dependencies needed by `discord.py` / HTTP libs (minimal).
- Copy source code into image.
- Install Python dependencies via `pip` (from `requirements.txt`).
- Create `/app/data` (or similar) directory where SQLite DB will live.
- Default `CMD` or `ENTRYPOINT` runs the bot (e.g., `python -m coc_bot` or `python bot.py`).

**Volume**:
- The SQLite DB file should live under a directory that will be bound to a Docker named volume:
  - Example: `-v coc-bot-data:/app/data`.

#### 9.3 EC2 + Elastic IP + systemd

**EC2 Instance**:
- Free-tier-eligible instance (e.g., `t3.micro` / `t4g.micro` variant depending on region and image).
- Amazon Linux or other mainstream Linux distro.
- Attach an **Elastic IP** and associate it with the instance; use this IP in CoC API key IP whitelist.

**Docker**:
- Install Docker, start and **enable** daemon at boot:
  - `sudo systemctl enable docker`

**Systemd Unit** (pattern adapted from CS351 “Surviving a reboot”):
- Create `/etc/systemd/system/coc-bot.service`:
  - `[Unit]`
    - `Description=Clash of Clans Discord bot`
    - `After=docker.service`
    - `Requires=docker.service`
  - `[Service]`
    - `Restart=always`
    - `ExecStartPre=-/usr/bin/docker stop %n`
    - `ExecStartPre=-/usr/bin/docker rm %n`
    - `ExecStart=/usr/bin/docker run --rm --name %n --env-file /path/to/coc-bot.env -v coc-bot-data:/app/data coc-bot:latest`
    - `ExecStop=/usr/bin/docker stop %n`
  - `[Install]`
    - `WantedBy=multi-user.target`
- Then:
  - `docker volume create coc-bot-data`
  - `sudo systemctl daemon-reload`
  - `sudo systemctl enable --now coc-bot.service`

This ensures:
- Container starts at boot.
- If the bot process exits, systemd restarts the service.
- SQLite DB persists across container restarts and instance reboots through the named volume.

### 10. Open Source Friendliness

- Repository should include:
  - Clear README explaining:
    - How to obtain Discord and CoC API tokens.
    - How to configure CoC IP whitelist with the EC2 Elastic IP.
    - How to build/run locally with Docker.
    - How to deploy to EC2 (high-level steps).
  - `Dockerfile`, `docker-compose.yml` (optional for local testing), and `requirements.txt`.
  - Example `.env.example` file with placeholders for tokens and config.
- Code should:
  - Avoid hard-coding paths or secrets.
  - Treat absence of certain features (like results channel, capital channel) gracefully.

### 11. Implementation Priorities for Claude Code

When implementing, follow roughly this order:

1. **Core bot skeleton**:
   - Basic Discord client, config loading from env, and simple `!ping` or `!status` command.
2. **SQLite persistence layer**:
   - Define schema (using migrations or raw SQL) for `guild_config`, `user_links`, `wars`, `reminders_sent`.
   - Implement data access functions.
3. **CoC API client**:
   - Minimal wrapper with authentication and basic error handling.
4. **War polling loop**:
   - Fetch current war, compute time remaining, log to console.
5. **Reminder logic**:
   - Threshold checks, `reminders_sent` dedupe, reminder message composition and sending.
6. **Linking commands**:
   - `!link`, `!unlink`, `!unlinkall`, `!links` wired to DB.
7. **War summary**:
   - Detect war end and post a one-time summary.
8. **Clan capital summary** (basic version).
9. **Dockerfile + local Docker run**:
   - Confirm bot works in container using SQLite on a volume.
10. **Deployment notes / systemd unit template**:
   - Provide example unit file and documentation in README for AWS EC2 deployment.


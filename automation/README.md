# Wen Shorts cloud publisher

This automation monitors YouTube channel RSS feeds, looks for creator-authorized source media in a private Cloudflare R2 bucket, creates one captioned vertical Short, and uploads it to the connected YouTube channel.

## Important media-rights boundary

The monitor reads public channel metadata only. It does **not** download media from YouTube. A source video is processed only when the authorized owner has placed the corresponding original media file in R2 at:

`authorized/VIDEO_ID.mp4`

Use only your own videos or media for which you have explicit permission to edit and republish. A public YouTube URL is not permission to download or reuse the video.

## Configure monitored channels

Copy `channels.example.json` to `channels.json` and replace the example with real YouTube channel IDs:

```json
{
  "channel_ids": ["UCxxxxxxxxxxxxxxxxxxxxxx"],
  "max_items_per_channel": 10
}
```

Commit `automation/channels.json` to the repository. Channel IDs are public identifiers, not secrets.

## Cloudflare R2

Create a private bucket. Create an R2 API token with Object Read & Write access limited to this bucket. Add these GitHub repository Actions secrets:

- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET`

Upload each authorized original as `authorized/VIDEO_ID.mp4`. The RSS feed discovers the video ID, but the source file must be supplied by the rights holder. The pipeline never attempts to fetch the video bytes from YouTube.

The state file is stored at `state/shorts-queue.json` in the same private bucket.

## YouTube OAuth

In Google Cloud Console:
1. Create or select a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen.
3. Create an OAuth client of type **Desktop app**.
4. Add the OAuth client ID and secret to GitHub Actions secrets as `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`.
5. Generate a refresh token locally with the Google OAuth flow using the scope `https://www.googleapis.com/auth/youtube.upload`, then save it as `YOUTUBE_REFRESH_TOKEN` in GitHub Actions secrets.

Never commit client secrets, refresh tokens, or R2 credentials. Keep the Google OAuth app in an appropriate publishing status for your account.

## Schedule

GitHub Actions runs at 12:00, 17:00 and 22:00 UTC, which is 09:00, 14:00 and 19:00 in São Paulo (UTC-3). GitHub scheduled workflows can be delayed during high load. The workflow publishes at most one Short per run, so the target is three per day, not a guaranteed delivery SLA.

## Output

The renderer uses FFmpeg and faster-whisper (tiny, CPU/int8), outputs 720x1280 H.264/AAC with Portuguese subtitles, and adds no watermark. A single best-scoring speech segment is selected heuristically. Review quality periodically; this is not semantic editorial judgment.

## Free-tier caveats

GitHub Actions, R2 and YouTube API have quotas and policies. Public repositories currently receive free standard GitHub-hosted runner minutes, but processing can still time out. R2 has storage and operation limits. YouTube API quota and OAuth restrictions apply. This design aims for zero recurring spend within free allowances, not unlimited free compute.

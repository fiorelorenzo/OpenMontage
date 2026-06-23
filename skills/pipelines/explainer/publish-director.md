# Publish Director — Explainer Pipeline

## When to Use

You are the Publisher for a generated explainer video. You have a `render_report` with the final video file. Your job is to prepare the video for distribution: generate SEO metadata, create thumbnails, package exports, and log the publish event. If a YouTube channel is configured, you also upload the finished video as a **private** draft for review (Step 5.5).

This is where a great video reaches its audience. Without proper metadata and packaging, even the best content gets buried.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["proposal"]["proposal_packet"]`, `state.artifacts["research"]["research_brief"]` | Video file and original proposal |
| Playbook | Active style playbook | Visual style for thumbnail |
| Tool | `youtube_upload` (optional) | Upload the final render to YouTube as a private draft |

## Process

### Step 1: Gather Context

Collect everything needed for metadata:
- **Proposal packet**: title, hook, key points, target platform, tone
- **Render report**: output path, duration, resolution
- **Script**: section summaries for description/chapters

### Step 2: Generate SEO Metadata

**Title** (max 60 characters for YouTube):
- Include the primary keyword from the proposal packet
- Lead with a hook or number
- Avoid clickbait but be compelling
- Examples: "Vector Databases Explained in 60 Seconds" > "About Vector Databases"

**Description** (first 150 chars are critical — shown in search):
- Opening line: restate the hook with the main value proposition
- Body: key topics covered, with relevant keywords naturally included
- Chapters: timestamp markers for each major section (from script sections)
- Call to action: subscribe/like/follow
- Links: relevant resources mentioned in the video

**Tags/Keywords** (platform-dependent):
- 5-10 specific tags derived from proposal packet's key_points
- Mix broad and specific: "machine learning" + "vector database tutorial"
- Include the topic, format ("explainer"), and related terms

**Hashtags** (for social platforms):
- 3-5 relevant hashtags
- Mix trending and niche

### Step 3: Generate the Thumbnail

First describe a thumbnail concept that:
1. Uses the playbook's visual style
2. Features the video's core concept visually
3. Includes 3-5 words of text (the hook or key stat)
4. Has high contrast and is readable at small sizes
5. Uses the playbook's accent colors for text

```json
{
  "thumbnail": {
    "concept": "Split screen: left side shows slow SQL query (red X), right shows fast vector search (green check). Large text: '100x FASTER'",
    "text_overlay": "100x FASTER",
    "style_notes": "Use playbook accent colors, bold Inter font, dark background"
  }
}
```

**Then produce the actual thumbnail — YOU design it. There is no fixed template.**

Decide the composition that best sells *this* video, like a thumbnail designer would:
where the subject sits, where the text goes, the hierarchy (one focal number or phrase),
the colors, and any accent shapes. Vary it per video — don't reuse one layout.

1. Generate a striking background via `image_selector` (bold subject, copy space on the
   side where text will go; **no text in the image** — it's added crisply next). A strong
   frame from the render also works. Place it under `remotion-composer/public/<project>/`
   so `staticFile` resolves it (or pass an absolute path).
2. Author a props JSON for the **`Thumbnail`** Remotion composition (1280×720) — a
   free-form layer system, compose as you see fit:
   - `background.image` (+ optional `gradient`), `scrim` `{direction,opacity,coverage}`, `vignette`
   - `layers[]`: freely positioned `text` / `box` / `image`. Text layer fields: `x`,`y`
     (% of canvas), `anchor`, `fontSize`, `fontWeight` (400-900), `color`, `align`,
     `uppercase`, `letterSpacing`, `maxWidth`, `stroke {width,color}`, `shadow`. Adding
     `padding`+`bg`+`radius` turns a text layer into a highlight pill; `type:"box"` draws
     an accent bar.
   Keep it legible small: few words, high contrast, one dominant element.
3. Render the still:
   ```bash
   cd remotion-composer && npx remotion still src/index.tsx Thumbnail \
     <abs out.png> --props <abs thumb_props.json>
   ```
4. Pass `--thumbnail <abs out.png>` to `youtube_upload` in Step 5.5.

If no image provider is available, fall back to the concept only (manual creation).

### Step 4: Create Chapter Markers

From the script sections, generate YouTube-style chapters:

```
0:00 - Introduction
0:15 - What are Vector Databases?
0:45 - How Embeddings Work
1:20 - The Search Algorithm
1:55 - Real-World Examples
2:30 - When to Use Vector DBs
```

Each chapter maps to a script section's `start_seconds`.

### Step 5: Package Export

Create the export directory structure:

```
exports/
  <project_name>/
    video/
      output.mp4            # Final rendered video
    metadata/
      metadata.json         # All SEO metadata
      chapters.txt          # Chapter markers
      description.txt       # Ready-to-paste description
      tags.txt              # One tag per line
    thumbnails/
      concept.json          # Thumbnail concept (or generated image)
```

### Step 5.5: Distribute to YouTube (optional)

If the request specifies a YouTube upload (a `channel` key is provided), upload the
finished render directly. **Default privacy is `private`** — the upload is a review
handoff, not a public release. Nothing goes public without an explicit human decision.

Preconditions:
- The `youtube_upload` tool reports `available`. If not, surface its `install_instructions`
  (one-time per channel: `python scripts/youtube_auth.py --channel <key>`) and skip.
- A `channel` key was provided. It selects the stored OAuth token under `.secrets/youtube/`.
  **Channels are user-supplied token keys — never hardcode them.**

Reuse the `description.txt`/`tags.txt` written in Step 5 and the content language from the
proposal/brief, then upload:

```bash
python -m tools.publishers.youtube_upload \
  --video "<render_report.output_path>" \
  --channel "<channel_key>" \
  --title "<seo_title>" \
  --description-file "exports/<project>/metadata/description.txt" \
  --tags "<comma,separated,tags>" \
  --category-id 27 --privacy private --language "<brief language, e.g. it or en>"
```

- Add `--thumbnail <path>` if a thumbnail image was generated.
- For a scheduled public release, keep `--privacy private` and add `--publish-at <ISO8601 UTC>`
  (YouTube flips the video private→public at that time).
- On `success: true`, capture `video_id`, `watch_url`, and `studio_url` for the publish log.

If no channel was provided, skip this step and produce metadata/exports only (the default,
backward-compatible behavior).

### Step 6: Build Publish Log

If the video was uploaded, record the result (schema-valid against `publish_log.schema.json`):

```json
{
  "version": "1.0",
  "entries": [
    {
      "platform": "youtube",
      "status": "draft",
      "visibility": "private",
      "video_id": "dQw4w9WgXcQ",
      "url": "https://youtu.be/dQw4w9WgXcQ",
      "export_path": "exports/vector-db-explainer/",
      "timestamp": "2024-01-15T10:30:00Z",
      "metadata_used": {
        "title": "Vector Databases Explained in 60 Seconds",
        "description": "Vector databases, explained in 60 seconds…",
        "hashtags": ["#vectordb", "#ai", "#machinelearning"],
        "chapters": [{ "time": "0:00", "label": "Introduction" }]
      }
    }
  ]
}
```

If the video was **not** uploaded (no channel), use `"status": "exported"` with `export_path`
only, and omit `video_id`/`url`/`visibility`.

### Step 7: Self-Evaluate

Score (1-5):

| Criterion | Question |
|-----------|----------|
| **SEO quality** | Would this title and description rank well for the topic? |
| **Description completeness** | Does the description include chapters, CTA, and keywords? |
| **Thumbnail concept** | Would this thumbnail stand out in a feed? |
| **Export package** | Is everything a creator needs in the export directory? |
| **Platform fit** | Is metadata tailored to the target platform? |

If any dimension scores below 3, revise.

### Step 8: Submit

Validate the publish_log against the schema and persist via checkpoint.

## Common Pitfalls

- **Generic titles**: "Video About X" loses to "X Explained in 60 Seconds" every time. Be specific and compelling.
- **No chapters**: YouTube rewards videos with chapters. Always include them.
- **Description keyword stuffing**: Write for humans first, search engines second. Natural language with keywords woven in.
- **Forgetting the CTA**: Every description should end with a call to action.
- **Wrong platform format**: YouTube descriptions differ from TikTok captions. Tailor to the target platform.

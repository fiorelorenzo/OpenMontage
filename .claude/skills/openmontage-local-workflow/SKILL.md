---
name: openmontage-local-workflow
description: Use when running or changing the video pipeline in this fork (a render, a voiceover, a music mix, a thumbnail, a YouTube upload), when a tool reports "No module named ...", or when narration comes out too quiet or the music bed keeps ducking on every pause.
metadata:
  version: 1.0.0
  updated: 2026-08-24
  origin: authored
  source: harvested from ~/.claude/projects/-home-dev-Progetti-emdash/memory/openmontage-youtube-automation.md
  status: active
---

# Working in this fork

This file is fork-local on purpose: it lives under `.claude/` so it can never end up in
an upstream pull request. Everything upstream-bound stays in the repo's own `skills/`
tree and follows upstream conventions (English, Conventional Commits, `BaseTool`
contract, tool classes PascalCase without a `Tool` suffix).

## Run the pipeline from `local/working`

**Rule: run from `local/working`, never from a feature branch.** The clean, PR-able
branches (`feat/youtube-publisher`, `feat/replicate-image-provider`) each contain only
their own tool, so running a pipeline from one of them fails with `No module named ...`
for whatever the other adds. `local/working` is the branch that merges both.

That separation is deliberate: upstream's merged pattern is one provider tool per PR, so
each feature stays its own clean branch and `local/working` is only for running.

## The feature is native, with no custom orchestrator

The pipeline is driven by an ordinary natural-language request against
`animated-explainer`; the per-stage `human_approval_default` gates (proposal, script,
scene plan, publish) are the "human only on important decisions" model, and the upload
happens in the native `publish` stage. A personal `.claude/commands/youtube-video.md`
orchestrator existed once and was removed so the whole feature stays upstreamable.

Channels are generic: OAuth tokens live under `.secrets/youtube/<channel>.json`
(gitignored, never printed), and content language is a per-video brief input rather than
anything baked into the repo. `youtube_upload` defaults to `privacy=private`.

## Audio: three settings that were tuned by ear, then measured

**Rule: loudness-normalise the narration before mixing.** Raw TTS sits too quiet
(mean -27 dB); `loudnorm=I=-16:TP=-1.5` brought it to -20 dB.

**Rule: the music sidechain needs a long release, not a short one.**
`sidechaincompress=threshold=0.025:ratio=14:attack=10:release=3000` with the bed at
about `volume=0.26` plus fades. At a ~300 ms release the bed rises on every micro-pause,
which is the artefact that made the first mix unusable.

**Plan scripts at 155 to 165 wpm.** Voice `UgBBYS2sOqTuMpoF3BR0` reads neutral prose at
about 126 wpm but ran 165 to 170 wpm on a number-heavy script, so a 13-minute target is
about 2,100 words and 15 minutes is about 2,450. Sizing a script by the calibration
number alone produced a 9.6-minute video where 13 were wanted.

A re-mix is cheap (`-c:v copy`, audio only), but a re-upload is a **new** video: the
YouTube API cannot replace the media of an existing one.

## Thumbnails are designed per video, never templated

The mechanism is the flexible `Thumbnail` Remotion composition
(`remotion-composer/src/Thumbnail.tsx`, registered in `Root.tsx`, 1280x720): background,
scrim, and freely positioned text, box and image layers. The agent authors a props JSON
for each video and renders one frame with
`npx remotion still src/index.tsx Thumbnail <out.png> --props <props.json>`, then passes
`--thumbnail` to the upload. The rigid Pillow helper (`scripts/make_thumbnail.py`) was
removed for this reason: Lorenzo's explicit ask is that the layout varies per video.

## Environment facts worth not rediscovering

- No GPU on this box, so only cloud, stock and image-based paths work. Headless 1080p
  rendering is proven.
- Keys live in `.env`: `REPLICATE_API_TOKEN`, `ELEVENLABS_API_KEY`, `PEXELS` and
  `PIXABAY` (the latter two are what make `direct_clip_search` and `pixabay_music` free).
- `scripts/youtube_auth.py` needs an interactive terminal; on this box the tokens were
  minted through a copy-paste OAuth exchange instead.
- Cost reference for one 3-minute explainer: about $0.50, mostly voice and images.

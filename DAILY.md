# Daily digest procedure

Run each morning. Goal: one listenable episode combining every AI newsletter that arrived since the last run.

## 1. Collect
- Read `state.json` → `last_cutoff_unix`. Record the current time (`date -u +%s`) as the new cutoff before searching.
- Gmail (helmstettergreg@gmail.com) search: `label:"AI news" after:<last_cutoff_unix>`. Fetch each with PLAIN_TEXT.
- Skip non-newsletter mail the label catches, e.g. Built In "Job Matches" job alerts. Built In "Editors' Picks" is fine (use only AI-related items).
- If nothing qualifies: update `state.json` cutoff, commit, push, and stop (no episode).

## 2. Write `scripts/YYYY-MM-DD.txt` (today's Mountain-time date)
- Written to be heard, not read: no URLs, no "click here", no emoji, no markdown, no bullet characters.
- Open: "Good morning. This is your AI news digest for <Weekday>, <Month> <day>. Today's episode draws on <newsletter names>." Close: "That's the digest for today. Have a good workout."
- Lead with the biggest stories. When several newsletters cover the same story, tell it ONCE, combining their details. Group related items (e.g. several stories about one company).
- Drop all sponsored content, ads, referral pitches, job listings, and newsletter housekeeping.
- Stay faithful to the sources: no facts beyond what the newsletters say; keep their hedges ("reportedly", "alleged", "claims").
- Spell for the ear: "A.I.", "C.E.O.", "four point eight billion dollars", "G.L.M. five point three".
- Target 800–1,300 words (about 6–9 minutes). Separate paragraphs with blank lines (the TTS chunks on paragraphs).

## 3. Write `scripts/YYYY-MM-DD.json`
`{"title": "<Dow Mon D>: <3 headline topics>", "description": "Sources: ... Stories: ..."}`

## 4. Publish
- Set `state.json` `last_cutoff_unix` to the cutoff recorded in step 1.
- `git add -A && git commit && git push origin main`. The GitHub Action voices it with Gemini TTS and updates the feed at https://ghelmstetter.github.io/ai-news-digest/feed.xml.
- Confirm a few minutes later that `git ls-remote origin gh-pages` changed / `git fetch origin gh-pages && git show origin/gh-pages:feed.xml | grep <today's date>` shows the new episode.

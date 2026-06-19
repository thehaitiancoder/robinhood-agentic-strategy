# Codex Automation Mirrors

This directory mirrors the live Codex automation definitions stored outside the
repo at:

`C:\Users\ralph\.codex\automations\<automation-id>\automation.toml`

Codex reads the live files from `C:\Users\ralph\.codex\automations`, not from
this directory. Keep these mirror files in git so automation prompt, schedule,
status, model, and workspace changes can be reviewed with normal diffs before
they are applied to the live Codex automation files.

When changing automations:

1. Update the matching mirror file here first.
2. Review and commit the repo diff.
3. Apply the same change to the live automation through the Codex automation
   tool or by carefully editing the live file when the tool cannot preserve the
   existing prompt safely.
4. Re-copy the live file back into this mirror after applying the change.

# Day 1 — Platform feasibility: join capability

Status: **in progress**. This document records verified evidence only; no platform has been selected.

## Test matrix

| Platform | Q1: Agent can join? | Evidence | Day 2 / 3 verification still needed |
| --- | --- | --- | --- |
| Zoom | **Yes, technically** — the native Meeting SDK can join a meeting as a named, unauthenticated SDK user. Zoom's web Meeting SDK is explicitly not permitted for bots/AI notetakers, so this project must use Zoom RTMS for the production notetaker media path rather than automate a browser client. | [Meeting SDK join guide](https://developers.zoom.us/docs/meeting-sdk/linux/start-join-mtg-webinar/meetings/), [Meeting SDK browser policy](https://developers.zoom.us/docs/meeting-sdk/web/browser-support/) | Verify RTMS enrollment/authorization in a test account, receive audio (Q2), send voice (Q3), and participant persistence (Q4). |
| Google Meet | **Yes, conditionally** — the Meet Media API supports an app connecting to a conference on behalf of an OAuth user. It is Developer Preview and requires the Cloud project, OAuth principal, and all meeting participants to be enrolled in the Developer Preview Program. | [Meet Media API concepts](https://developers.google.com/workspace/meet/media-api/guides/concepts), [get started / access requirements](https://developers.google.com/workspace/meet/media-api/guides/get-started) | Enroll a test Workspace environment in Developer Preview, then verify media receive (Q2), whether it can publish voice (Q3), and persistence (Q4). |

## Day 1 conclusion

Both candidates have a documented joining route, but neither is selected. Zoom currently has the less experimental media option for a commercial notetaker: RTMS streams meeting media over WebSocket after the host enables/authorizes it. Google Meet Media API is viable for consumption but preview-gated. The Day 3 decision remains contingent on hands-on Q2–Q4 tests and account approvals.

## Guardrails confirmed now

- Do not automate Zoom's web Meeting SDK as a bot; Zoom reserves it for human use.
- Use least-privilege OAuth scopes and obtain explicit meeting/recording consent.
- Recording will remain off by default when that feature is built in Block 4.

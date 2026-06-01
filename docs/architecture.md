# Architecture notes

The README has the canonical diagram. Use this file for any longer diagram/image
(e.g. export a draw.io / Excalidraw PNG here and link it from the README).

Request flow: client -> (auth, rate limit) -> input guard -> retrieve + in-scope gate
-> grounded prompt (untrusted-delimited context) -> Groq -> output guard -> response.

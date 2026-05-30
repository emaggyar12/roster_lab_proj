# 247 Profile URL Fallback Notes

## Current scraper behavior

For each recruit, the scraper first tries the profile URL returned by the 247 recruits API.

Example:

```text
https://247sports.com/player/cody-larson-10576/
```

If that URL fails or does not produce height/weight, the scraper calls `discover_247_profile_url(...)`.

That fallback currently searches:

```text
DuckDuckGo HTML
Brave Search
```

It does **not** use Google.

## Why Google may work but the scraper may not

When searching manually, Google may show a valid 247 profile URL as the first result. The scraper is not using Google because Google search result HTML is harder to parse reliably and can hide/obfuscate result URLs.

The current code path is:

```text
API profile URL -> DuckDuckGo -> Brave
```

not:

```text
API profile URL -> Google
```

## Important URL detail

For some older recruits, the base profile URL returns `404`:

```text
https://247sports.com/player/darion-atkins-669/
```

But the college/career-specific profile URL works:

```text
https://247sports.com/player/darion-atkins-669/college-146398/
```

The trailing `college-XXXXX` segment appears to be a 247 internal player-institution/career record ID.

## Known issue

For Darion Atkins, Brave Search found the working `college-146398` URL.

For some 2010 missing players, broader DuckDuckGo/Brave searches did not return matching `college-...` URLs during the scraper run.

The unresolved 2010 players were:

```text
Cody Larson
Jalen Courtney
Jordan Sibert
Jelan Kendrick
Daniel Bejarano
Jordan Bachynski
Brian Williams
Will Regan
David Eads
Falando Jones
Kelvin Gaines
```

The scraper needs working 247 URLs that resolve to pages containing height/weight. If the base URL still returns `404`, the useful URL is likely a `college-XXXXX` version.

## What would fix this

Possible approaches:

1. Find a reliable API/source that maps `player_key` to the correct `college-XXXXX` URL.
2. Add Google Custom Search or another reliable search API rather than scraping Google HTML.
3. Manually provide `college-XXXXX` URLs for unresolved players.
4. Use another source for missing height/weight when 247 profile pages cannot be resolved.


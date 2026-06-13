It's essentially just a wrapper for yt-dlp, so let's keep things as simple as this thing.

Its what I was looking for to self-host, didn't find anything this simple so I built it. If it's of any value to you at all, I'm of course extremely happy if you contribute.

No tickets or anthing annoying, but I do try my best to keep this readable though, please do the same:

- Let comments say *why* something's done. 

- Every push/PR runs flake8 and ESLint.. nothing strict, just no dead code or obvious mess, and Python lines stay under 120.

- There are a few pytests around the fiddly parts. Grab the dev tools with `pip install --group dev`, then run `pytest`. If you touch that logic, add or tweak a test.

- Runtime deps stay pinned. Dev/test tools go in `pyproject.toml` under `[dependency-groups]`, not the runtime list.

### How to contribute

1. **Fork it.**
2. **Hack on it.** Change whatever you want.
3. **Open a PR.** Just leave a quick note on what you changed and why.

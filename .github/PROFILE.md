The profile uses Caveat handwriting throughout: signature, introduction, project descriptions, section headings, navigation, and statistics. Text is rendered as SVG paths because README content cannot set a custom font. SVGs have light and dark variants selected by GitHub's themed pictures; paragraphs and section headings also have mobile layouts with reflowed lines. Project copy lives in `draw_content()` in the generator. Links and full text alternatives live in README.md. Tool logos remain separate, clickable images. Links inside themed pictures wrap the fallback image so GitHub can preserve both the destination and theme selection.

Visual references: [antfu](https://github.com/antfu/antfu), [DenverCoder1](https://github.com/DenverCoder1/DenverCoder1), and the [Awesome Profile README gallery](https://github.com/abhisheknaiidu/awesome-github-profile-readme). The layout uses compact sections and restrained iconography; no artwork was copied from those profiles.

Tool marks are stored locally to avoid runtime icon-service dependencies: [VS Code's official assets](https://code.visualstudio.com/brand), [Antigravity's official press kit](https://antigravity.google/press), and the [GitHub mark from Simple Icons](https://github.com/simple-icons/simple-icons/blob/develop/icons/github.svg) (CC0 icon collection; brand trademarks remain with their owners). The GitHub mark uses a sage fill visible in both themes.

`profile.yml` redraws the SVGs daily at 05:23 UTC, on generator changes, and on manual dispatch. GitHub may delay scheduled runs. The workflow starts once these files are pushed to the default branch. It uses the built-in `GITHUB_TOKEN`; no personal access token or hosting is needed. Repository policies must allow Actions to write contents. GitHub may disable schedules in inactive public repositories after 60 days; a manual run or schedule edit can re-enable them.

To regenerate locally with an authenticated GitHub CLI:

```sh
python -m pip install -r scripts/requirements.txt
python -m unittest discover -s tests
python scripts/update_profile.py
```

Statistics:

- Languages aggregate GitHub's reported byte counts across all owned public non-fork projects, excluding the profile repository to avoid counting the generated artwork. The largest five languages are shown individually and the rest grouped as Other; the SVG description contains the full breakdown. Percentages are rounded to tenths with a total of 100%. This measures code size, not expertise or authorship, and includes AI-assisted project code. Updated daily with the other artwork. See [GitHub's language endpoint](https://docs.github.com/en/rest/repos/repos#list-repository-languages).
- Total stars sums stars on all public repositories owned by the account, including its forks, with pagination. It does not count stars on upstream repositories.
- The calendar uses GitHub's contribution calendar for the last 365 days. The current streak counts consecutive active dates, allowing today to be unfinished, using UTC. Older history is fetched if the streak extends past the calendar. Visibility follows the API token's access; the scheduled token does not grant access to other private repositories.
- Profile views uses the existing Komarev counter for `GoulagmanYt`. A one-pixel image in the README registers GitHub image-proxy requests; the generator reads the value with its own user agent, which does not increment it. The number is a daily snapshot of cumulative recorded page hits, not unique visitors or an all-time GitHub analytics total. Caching and bots affect it. If the counter fails, the panel says unavailable until a successful refresh. See [the counter's documentation](https://github.com/antonkomarev/github-profile-views-counter) and [request handling](https://github.com/antonkomarev/github-profile-views-counter/blob/master/public/index.php).

Artwork uses the bundled [Caveat font](https://github.com/google/fonts/tree/main/ofl/caveat) under the adjacent SIL Open Font License. Lettering is converted to SVG paths, so GitHub displays the actual handwriting without installed fonts, external fonts, scripts, or animation. The SVG title, description, and README image alternatives provide text equivalents.

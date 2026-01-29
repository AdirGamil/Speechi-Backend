# Fonts for PDF export

PDF export uses WeasyPrint (HTML → PDF). To render **Hebrew**, **Arabic**, and Latin scripts correctly (no ■■■■ squares), place font files in this directory.

## Recommended fonts

| Family             | Use      | Suggested filename(s)        | Source |
|--------------------|----------|------------------------------|--------|
| Heebo              | Hebrew   | `Heebo-Regular.woff2`, `.woff` | [Google Fonts](https://fonts.google.com/specimen/Heebo) |
| Noto Sans Arabic   | Arabic   | `NotoSansArabic-Regular.woff2`, `.woff` | [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+Arabic) |
| Noto Sans          | Latin    | `NotoSans-Regular.woff2`, `.woff` | [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans) |

The service looks for these filenames and embeds them in the PDF via `@font-face`. If no files are present, WeasyPrint falls back to system/default fonts (Hebrew and Arabic may not render correctly).

## Optional: system fonts (Linux)

On Debian/Ubuntu you can install system fonts; WeasyPrint may pick them up:

```bash
sudo apt-get install fonts-noto fonts-noto-core fonts-hebrew
```

For consistent, embedded output across environments, prefer placing the font files in this directory.

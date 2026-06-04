# Etsy Product Pipeline

A local desktop workflow for preparing digital product assets and creating Etsy
draft listings in bulk.

This project combines two related tools:

- `asset_pipeline`: batch file and image preparation for digital products.
- `listing_pipeline`: Etsy draft listing creation and upload workflow.

It was designed for high-volume digital download workflows where product assets
need to be prepared, packaged, reviewed, and uploaded consistently.

## What it demonstrates

- Python desktop application development.
- Batch image processing with Pillow.
- Local file pipeline automation.
- ZIP packaging with size limits.
- Optional local image/video processing.
- Etsy OAuth and API integration.
- Draft listing automation.
- Optional local metadata enrichment through Ollama.

## Repository structure

```text
etsy-product-pipeline-public/
  asset_pipeline/
    asset_pipeline_gui.py
    settings_unified.example.json

  listing_pipeline/
    main.py
    gui_components.py
    etsy_operations.py
    etsy_oauth.py
    ai_metadata.py
    templates.example.json

  .env.example
  .gitignore
  requirements.txt
  README.md
```

## Privacy and setup note

This public version does not include real tokens, real Etsy app credentials,
real shop IDs, private listing templates, logs, generated files, or local machine
paths.

Before using it, you must create your own configuration from the example files.

## License and usage

This repository is shared as a portfolio/code sample. No open-source license is
granted. You may read the code for review, but reuse, redistribution, or
commercial use requires explicit permission from the author. See `LICENSE` for
details.

## Installation

Use Python 3.10 or 3.11.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Environment variables

Copy:

```text
.env.example
```

to:

```text
.env
```

Then fill in your own values:

```text
ETSY_CLIENT_ID
ETSY_CLIENT_SECRET
ETSY_SHOP_ID
ETSY_REDIRECT_URI
ETSY_OAUTH_STATE
ETSY_TEMPLATES_FILE
PRODUCT_NAME_SUFFIXES
```

Optional values:

```text
OLLAMA_URL
OLLAMA_MODEL
WAIFU2X_EXE
REALESRGAN_EXE
REALESRGAN_MODEL_DIR
REALESRGAN_MODEL_NAME
```

PowerShell example:

```powershell
$env:ETSY_CLIENT_ID="your_etsy_client_id"
$env:ETSY_CLIENT_SECRET="your_etsy_client_secret"
$env:ETSY_SHOP_ID="your_etsy_shop_id"
```

If your prepared product folders include a brand suffix that should be removed
from listing names, set:

```powershell
$env:PRODUCT_NAME_SUFFIXES="YourBrandName,AnotherSuffix"
```

## Etsy developer setup

To use the listing uploader with a real shop, create your own Etsy developer
application first:

1. Go to the Etsy Developer portal and create a new app.
2. Set your redirect URI, for example:

   ```text
   http://localhost:8080/callback
   ```

3. Copy your own app key and client secret into `ETSY_CLIENT_ID` and
   `ETSY_CLIENT_SECRET`.
4. Copy your own shop ID into `ETSY_SHOP_ID`.
5. Run the OAuth step from the listing pipeline section below.

No Etsy credentials are included in this repository.

## Asset pipeline

Location:

```text
asset_pipeline/asset_pipeline_gui.py
```

Run:

```powershell
python asset_pipeline/asset_pipeline_gui.py
```

Optional setup:

1. Copy `asset_pipeline/settings_unified.example.json`.
2. Rename the copy to `asset_pipeline/settings_unified.json`.
3. Adjust local paths and options.

The asset pipeline can:

- unzip product packages,
- flatten and rename image files,
- batch upscale images through local external tools,
- create clean and watermarked output folders,
- create ZIP packages under a configured size limit,
- optionally create video previews.

Upscale is optional. If you want to use it, set:

```text
REALESRGAN_EXE
REALESRGAN_MODEL_DIR
REALESRGAN_MODEL_NAME
```

or adapt the settings for your own local upscale tool.

## Listing pipeline

Location:

```text
listing_pipeline/main.py
```

Run:

```powershell
python listing_pipeline/main.py
```

Before uploading to Etsy:

1. Set `ETSY_CLIENT_ID`, `ETSY_CLIENT_SECRET`, and `ETSY_SHOP_ID`.
2. Run OAuth:

   ```powershell
   python listing_pipeline/etsy_oauth.py
   ```

3. This creates local `access_token.txt` and `refresh_token.txt`.
4. Load prepared products in the GUI.
5. Use the Etsy API test action before upload.
6. Upload creates draft listings, not directly published live listings.

## Templates

The public repo includes:

```text
listing_pipeline/templates.example.json
```

Use it as a starting point. For real use, create your own template file and set:

```text
ETSY_TEMPLATES_FILE=path/to/your/templates.json
```

The example template uses placeholder values, not real shop copy:

```text
{{nazev}} = product or folder name
<<x>>     = number of detected image/files for the listing
```

Example:

```text
{{nazev}} Digital Download - <<x>> Files
```

Before uploading to a real Etsy shop, replace the example description, tags,
license terms, delivery notes, printing notes, price, taxonomy, and any shop
policy text with your own content.

## Optional metadata enrichment

The listing pipeline includes optional local metadata enrichment logic through
Ollama.

Default values:

```text
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=qwen3-vl:8b
```

This step is optional. The Etsy listing workflow can still be used manually
without running Ollama.

## Files intentionally excluded

This public version intentionally excludes:

- `access_token.txt`
- `refresh_token.txt`
- real Etsy credentials,
- real shop ID,
- private product templates,
- generated product output,
- logs,
- `__pycache__`,
- local virtual environments,
- local absolute tool paths.

## Current status

This is a portfolio/public-safe extraction of a larger private workflow. The
code is functional-oriented and intentionally kept close to the original tool,
but a production-grade release would benefit from:

- cleaner module boundaries,
- stronger config loading,
- test fixtures,
- a dedicated CLI mode,
- improved error handling,
- screenshots and sample data,
- a safer dry-run workflow for uploads.

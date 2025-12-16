# Vehicle Assets Repository

This repository contains **web-optimized** assets for the vehicle project. High-resolution originals and videos are hosted externally on Google Drive to maintain repository performance and optimization for web frameworks (like Nuxt).

## 🚀 Workflows

### 1. Adding New Assets
The **Google Drive folder** is the Source of Truth.
1.  Upload your photos or videos to the corresponding vehicle folder in Google Drive.
2.  Run the sync script locally:
    ```bash
    python asset_manager.py sync
    ```
3.  Commit and push the changes:
    ```bash
    git add .
    git commit -m "Sync assets from Drive"
    git push
    ```

### 2. Using Assets in Your App
Use `assets.json` to find the correct path for any media file.
- **Images**: Use the `optimized_path` (local in this repo) for standard display. Use `original_path` (remote) only for download links.
- **Videos**: Videos are only available remotely. Use the `original_path` combined with your Drive base URL.

## 📂 Structure
- `assets.json`: The manifest database linking every asset to its local and remote locations.
- `[Vehicle_Folders]`: Contain optimized JPEGs (max 1920px width).
- `asset_manager.py`: The automation script for syncing.

## 🛠 Setup
To run the sync script, ensure you have Python 3 and Pillow installed:
```bash
pip install Pillow
```
Configured Drive Backup Path (Local): `/Users/prasanthsasikumar/Downloads/vehicles_drive_backup`
*(Update `DRIVE_PATH` in `asset_manager.py` if your location changes)*

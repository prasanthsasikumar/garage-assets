import os
import shutil
import json
import argparse
import logging
from PIL import Image
import mimetypes

# Configuration
REPO_PATH = '/Users/prasanthsasikumar/Downloads/vehicles'
# Validating user path: User mentioned "keeping these files in a repo". 
# The current files are in REPO_PATH.
# We need a "Drive Path". Since we are simulating or preparing for Drive, 
# we'll use a sibling directory `vehicles_drive_backup` as the "Drive" folder.
DRIVE_PATH = '/Users/prasanthsasikumar/Downloads/vehicles_drive_backup'
MANIFEST_FILE = os.path.join(REPO_PATH, 'assets.json')

# Optimization Settings
MAX_WIDTH = 1920
JPEG_QUALITY = 85

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def setup_logging():
    pass # Already done above

def is_image(filename):
    mtype, _ = mimetypes.guess_type(filename)
    return mtype and mtype.startswith('image')

def is_video(filename):
    mtype, _ = mimetypes.guess_type(filename)
    return mtype and mtype.startswith('video')

def optimize_image(src_path, dest_path):
    """
    Resizes image to max width 1920px, converts to JPEG/RGB, and saves.
    """
    try:
        with Image.open(src_path) as img:
            # Convert to RGB if necessary (e.g. PNG with alpha, or CMYK)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            width, height = img.size
            if width > MAX_WIDTH:
                new_height = int(height * (MAX_WIDTH / width))
                img = img.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)
            
            # Save as optimized JPEG
            # ensure dest_path ends with .jpg if we are forcing jpeg
            base, _ = os.path.splitext(dest_path)
            final_dest = base + ".jpg"
            
            img.save(final_dest, 'JPEG', quality=JPEG_QUALITY, optimize=True)
            return final_dest
    except Exception as e:
        logging.error(f"Failed to optimize {src_path}: {e}")
        return None


def is_markdown(filename):
    return filename.lower().endswith('.md')

def parse_frontmatter(path):
    """
    Parses basic YAML frontmatter between --- lines.
    Returns a dictionary of metadata.
    """
    metadata = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Check if file starts with frontmatter delimiter
        if not lines or lines[0].strip() != '---':
            return metadata
        
        for line in lines[1:]:
            line = line.strip()
            if line == '---':
                break
            if ':' in line:
                key, value = line.split(':', 1)
                # Try to cast to number if possible
                val = value.strip()
                try:
                    if '.' in val:
                         val = float(val)
                    else:
                         val = int(val)
                except ValueError:
                    pass # Keep as string
                
                metadata[key.strip()] = val
    except Exception as e:
        logging.warning(f"Failed to parse frontmatter for {path}: {e}")
    
    return metadata


def migrate():
    """
    One-time migration:
    1. Move EVERYTHING from Repo to Drive (preserving structure).
    2. For Images: Generate optimized copy back in Repo.
    3. For Videos: Leave in Drive only.
    4. Generate Manifest.
    """
    logging.info("Starting Migration...")
    
    if not os.path.exists(DRIVE_PATH):
        os.makedirs(DRIVE_PATH)
        logging.info(f"Created Drive folder at {DRIVE_PATH}")

    assets = []

    # Iterate strictly over directories in REPO_PATH
    # We want to catch the top-level vehicle folders (e.g., Mazda_RX8_Purple)
    for root, dirs, files in os.walk(REPO_PATH):
        # specific skip for .git or specific ignores if any
        if '.git' in root:
            continue
            
        # Determine relative path from Repo Root
        rel_dir = os.path.relpath(root, REPO_PATH)
        
        if rel_dir == '.':
            # We are in root. We might want to skip root files unless they are assets?
            # The user has files inside subdirectories. 
            pass
        
        # Ensure corresponding directory exists in Drive
        drive_root = os.path.join(DRIVE_PATH, rel_dir)
        if not os.path.exists(drive_root):
            os.makedirs(drive_root)
            
        for filename in files:
            if filename.startswith('.') or filename == 'assets.json' or filename == 'large_files_log.txt' or filename.endswith('.py') or filename == 'README.md' or filename == '_headers':
                continue
                
            original_path = os.path.join(root, filename)
            drive_path = os.path.join(drive_root, filename)
            
            # 1. Move Original to Drive
            # Skip moving if it's already there (idempotent) or if it's a markdown file (keep MD local)
            if is_markdown(filename):
                # Markdown stays in repo, do not move to drive logic for now or copy?
                # Per plan: MD is source of truth in Repo. 
                pass
            else:
                 logging.info(f"Moving {filename} to {drive_path}...")
                 shutil.move(original_path, drive_path)
            
            asset_entry = {
                "original_path": os.path.join(rel_dir, filename),
                "type": "unknown",
                "location": "remote"
            }

            # 2. Process based on type
            if is_image(filename):
                asset_entry["type"] = "image"
                # Generate optimized version in Repo
                dest_optimized = os.path.join(root, filename) # will be replaced with .jpg
                final_optimized_path = optimize_image(drive_path, dest_optimized)
                
                if final_optimized_path:
                    # Rel path of optimized file
                    rel_opt_path = os.path.relpath(final_optimized_path, REPO_PATH)
                    asset_entry["optimized_path"] = rel_opt_path
                    asset_entry["location"] = "hybrid" # Both remote and local-optimized
            
            elif is_video(filename):
                asset_entry["type"] = "video"
                # Videos stay remote only.
            
            elif is_markdown(filename):
                asset_entry["type"] = "markdown"
                asset_entry["location"] = "local" # Stays in repo
                asset_entry["metadata"] = parse_frontmatter(original_path)

            assets.append(asset_entry)

    # Write Manifest
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(assets, f, indent=2)
    
    logging.info(f"Migration Complete. Manifest written to {MANIFEST_FILE}")


def sync():
    """
    Syncs changes from Drive to Repo.
    1. Scans Drive.
    2. If new image found -> Optimize and add to Repo.
    3. Update Manifest.
    """
    logging.info("Starting Sync...")
    
    # Load existing manifest to track what we know
    if os.path.exists(MANIFEST_FILE):
        with open(MANIFEST_FILE, 'r') as f:
            try:
                current_assets = json.load(f)
            except json.JSONDecodeError:
                current_assets = []
    else:
        current_assets = []

    # Map of known original paths to entries
    known_paths = {a['original_path']: a for a in current_assets}
    new_assets = []

    # 1. Scan Drive (for media)
    for root, dirs, files in os.walk(DRIVE_PATH):
        rel_dir = os.path.relpath(root, DRIVE_PATH)
        
        # Ensure local repo dir exists for optimization
        repo_dir = os.path.join(REPO_PATH, rel_dir)
        if not os.path.exists(repo_dir) and rel_dir != '.':
            os.makedirs(repo_dir)

        for filename in files:
            if filename.startswith('.'): 
                continue

            drive_path = os.path.join(root, filename)
            rel_path = os.path.join(rel_dir, filename)
            
            # Check if we already know this file
            if rel_path in known_paths:
                new_assets.append(known_paths[rel_path])
                continue
            
            # New File!
            logging.info(f"New file detected in Drive: {rel_path}")
            
            asset_entry = {
                "original_path": rel_path,
                "type": "unknown",
                "location": "remote"
            }

            if is_image(filename):
                asset_entry["type"] = "image"
                dest_optimized = os.path.join(repo_dir, filename)
                final_optimized_path = optimize_image(drive_path, dest_optimized)
                
                if final_optimized_path:
                     rel_opt_path = os.path.relpath(final_optimized_path, REPO_PATH)
                     asset_entry["optimized_path"] = rel_opt_path
                     asset_entry["location"] = "hybrid"
            
            elif is_video(filename):
                asset_entry["type"] = "video"
            
            new_assets.append(asset_entry)
            
    # 2. Scan Repo (for markdown/local files that are NOT in drive)
    for root, dirs, files in os.walk(REPO_PATH):
        if '.git' in root or 'node_modules' in root:
             continue
             
        rel_dir = os.path.relpath(root, REPO_PATH)
        
        for filename in files:
            if is_markdown(filename):
                rel_path = os.path.join(rel_dir, filename)
                
                # Check if exists in new_assets (it shouldn't came from Drive loop)
                # But check if it was in known_paths?
                
                # Always re-parse metadata for markdown files to capture updates
                full_path = os.path.join(root, filename)
                metadata = parse_frontmatter(full_path)

                exists = False
                for a in new_assets:
                    if a['original_path'] == rel_path:
                        # Update metadata if it exists
                        a['metadata'] = metadata
                        exists = True
                        break
                
                if not exists:
                     logging.info(f"New Markdown detected in Repo: {rel_path}")
                     asset_entry = {
                        "original_path": rel_path,
                        "type": "markdown",
                        "location": "local",
                        "metadata": metadata
                    }
                     new_assets.append(asset_entry)

    # Write Updated Manifest
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(new_assets, f, indent=2)
    
    logging.info("Sync Complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['migrate', 'sync'], help='migrate: initial move to drive; sync: update from drive')
    args = parser.parse_args()
    
    if args.command == 'migrate':
        migrate()
    else:
        sync()


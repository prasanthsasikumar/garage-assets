import os
import shutil
import json
import argparse
import logging
import copy
from PIL import Image, UnidentifiedImageError
import mimetypes
from datetime import datetime, timezone

try:
    from pillow_heif import register_heif_opener
except ImportError:
    register_heif_opener = None

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

MANIFEST_SCHEMA_VERSION = 2
MANIFEST_CATEGORIES = ('cars', 'motorcycles', 'garages')
DEFAULT_CATEGORY_BY_TYPE = {
    'car': 'cars',
    'motorcycle': 'motorcycles',
    'garage': 'garages',
}
DEFAULT_TYPE_BY_CATEGORY = {
    'cars': 'car',
    'motorcycles': 'motorcycle',
    'garages': 'garage',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

HEIF_SUPPORT_ENABLED = False
UNSUPPORTED_IMAGE_WARNINGS = set()

if register_heif_opener is not None:
    register_heif_opener()
    HEIF_SUPPORT_ENABLED = True

def setup_logging():
    pass # Already done above

def is_image(filename):
    mtype, _ = mimetypes.guess_type(filename)
    return mtype and mtype.startswith('image')

def is_video(filename):
    mtype, _ = mimetypes.guess_type(filename)
    return mtype and mtype.startswith('video')


def log_skipped_image(src_path, error):
    extension = os.path.splitext(src_path)[1].lower() or '<no extension>'

    if extension in {'.heic', '.heif'} and not HEIF_SUPPORT_ENABLED:
        warning_key = ('heif-missing', extension)
        if warning_key not in UNSUPPORTED_IMAGE_WARNINGS:
            logging.warning(
                'Skipping %s images because HEIC/HEIF support is not installed in the active environment.',
                extension,
            )
            UNSUPPORTED_IMAGE_WARNINGS.add(warning_key)
        return

    warning_key = (extension, type(error).__name__)
    if warning_key in UNSUPPORTED_IMAGE_WARNINGS:
        return

    logging.warning('Skipping unsupported image format %s: %s', extension, error)
    UNSUPPORTED_IMAGE_WARNINGS.add(warning_key)

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
    except UnidentifiedImageError as e:
        log_skipped_image(src_path, e)
        return None
    except OSError as e:
        log_skipped_image(src_path, e)
        return None
    except Exception as e:
        logging.error(f"Failed to optimize {src_path}: {e}")
        return None


def is_markdown(filename):
    return filename.lower().endswith('.md')


def default_vehicle_display_name(slug):
    return slug.replace('_', ' ')


def infer_vehicle_slug(rel_path):
    normalized = rel_path.replace('\\', '/')
    top_level = normalized.split('/', 1)[0]
    if top_level in ('', '.'):
        return None
    return top_level


def infer_category_for_vehicle(vehicle_data):
    vehicle_type = vehicle_data.get('type')
    return DEFAULT_CATEGORY_BY_TYPE.get(vehicle_type, 'cars')


def empty_asset_buckets():
    return {
        'images': [],
        'videos': [],
        'markdown': [],
        'other': [],
    }


def asset_bucket_name(asset_type):
    return {
        'image': 'images',
        'video': 'videos',
        'markdown': 'markdown',
    }.get(asset_type, 'other')


def load_existing_manifest():
    if not os.path.exists(MANIFEST_FILE):
        return None, {}, {}, {category: [] for category in MANIFEST_CATEGORIES}

    with open(MANIFEST_FILE, 'r') as f:
        try:
            manifest = json.load(f)
        except json.JSONDecodeError:
            return None, {}, {}, {category: [] for category in MANIFEST_CATEGORIES}

    known_paths = {}
    vehicle_info = {}
    vehicle_order = {category: [] for category in MANIFEST_CATEGORIES}

    if isinstance(manifest, list):
        for asset in manifest:
            if isinstance(asset, dict) and 'original_path' in asset:
                known_paths[asset['original_path']] = asset
        return manifest, known_paths, vehicle_info, vehicle_order

    if not isinstance(manifest, dict):
        return manifest, known_paths, vehicle_info, vehicle_order

    vehicles = manifest.get('vehicles', {})
    for category, entries in vehicles.items():
        if category not in vehicle_order:
            vehicle_order[category] = []
        for vehicle in entries:
            slug = vehicle.get('slug')
            if not slug:
                continue

            vehicle_order[category].append(slug)
            vehicle_info[slug] = {
                'category': category,
                'data': {
                    key: copy.deepcopy(value)
                    for key, value in vehicle.items()
                    if key not in {'assets', 'summary'}
                },
            }

            for bucket in vehicle.get('assets', {}).values():
                for asset in bucket:
                    if isinstance(asset, dict) and 'original_path' in asset:
                        known_paths[asset['original_path']] = copy.deepcopy(asset)

    return manifest, known_paths, vehicle_info, vehicle_order


def build_nested_manifest(collected_assets, vehicle_info, vehicle_order):
    assets_by_slug = {slug: empty_asset_buckets() for slug in vehicle_info}

    for rel_path, asset in collected_assets.items():
        slug = infer_vehicle_slug(rel_path)
        if not slug:
            continue
        assets_by_slug.setdefault(slug, empty_asset_buckets())
        bucket = asset_bucket_name(asset.get('type'))
        assets_by_slug[slug][bucket].append(asset)

    vehicles_out = {category: [] for category in MANIFEST_CATEGORIES}
    total_assets = 0
    total_vehicles = 0
    seen_slugs = set()

    for category in vehicle_order:
        for slug in vehicle_order[category]:
            seen_slugs.add(slug)

    for slug in assets_by_slug:
        if slug not in seen_slugs:
            category = vehicle_info.get(slug, {}).get('category')
            if not category:
                category = infer_category_for_vehicle(vehicle_info.get(slug, {}).get('data', {}))
            vehicle_order.setdefault(category, []).append(slug)

    for category in MANIFEST_CATEGORIES:
        ordered_slugs = vehicle_order.get(category, [])
        for slug in ordered_slugs:
            buckets = assets_by_slug.get(slug, empty_asset_buckets())
            normalized_buckets = {
                name: sorted(values, key=lambda asset: asset['original_path'].lower())
                for name, values in buckets.items()
            }

            vehicle_data = copy.deepcopy(vehicle_info.get(slug, {}).get('data', {}))
            vehicle_data.setdefault('slug', slug)
            vehicle_data.setdefault('display_name', default_vehicle_display_name(slug))
            vehicle_data.setdefault('type', DEFAULT_TYPE_BY_CATEGORY.get(category, 'car'))
            vehicle_data.setdefault('weight', 0)

            image_paths = []
            for image in normalized_buckets['images']:
                image_paths.append(image['original_path'])
                if image.get('optimized_path'):
                    image_paths.append(image['optimized_path'])

            thumbnail = vehicle_data.get('thumbnail_image')
            if thumbnail not in image_paths:
                if normalized_buckets['images']:
                    fallback = normalized_buckets['images'][0]
                    vehicle_data['thumbnail_image'] = fallback.get('optimized_path') or fallback['original_path']
                else:
                    vehicle_data.pop('thumbnail_image', None)

            summary = {
                'images': len(normalized_buckets['images']),
                'videos': len(normalized_buckets['videos']),
                'markdown': len(normalized_buckets['markdown']),
                'other': len(normalized_buckets['other']),
            }
            summary['total_assets'] = sum(summary.values())

            vehicle_data['summary'] = summary
            vehicle_data['assets'] = normalized_buckets
            vehicles_out[category].append(vehicle_data)

            total_assets += summary['total_assets']
            total_vehicles += 1

    return {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'summary': {
            'total_vehicles': total_vehicles,
            'total_assets': total_assets,
            'categories': {
                category: len(vehicles_out[category])
                for category in MANIFEST_CATEGORIES
            },
        },
        'vehicles': vehicles_out,
    }

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
                # Strip surrounding quotes (common in YAML frontmatter)
                if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                    val = val[1:-1]
                try:
                    if '.' in val:
                        val = float(val)
                    else:
                        val = int(val)
                except ValueError:
                    pass  # Keep as string
                
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
    _, known_paths, vehicle_info, vehicle_order = load_existing_manifest()
    collected_assets = {}

    # 1. Scan Drive (for media)
    for root, dirs, files in os.walk(DRIVE_PATH):
        dirs[:] = [directory for directory in dirs if not directory.startswith('.')]
        rel_dir = os.path.relpath(root, DRIVE_PATH)

        if rel_dir == '.':
            continue
        
        # Ensure local repo dir exists for optimization
        repo_dir = os.path.join(REPO_PATH, rel_dir)
        if not os.path.exists(repo_dir) and rel_dir != '.':
            os.makedirs(repo_dir)

        for filename in files:
            if filename.startswith('.'): 
                continue

            drive_path = os.path.join(root, filename)
            rel_path = os.path.join(rel_dir, filename)
            slug = infer_vehicle_slug(rel_path)
            if not slug:
                continue
            
            # Check if we already know this file
            known_entry = copy.deepcopy(known_paths.get(rel_path))
            asset_entry = known_entry or {
                "original_path": rel_path,
                "type": "unknown",
                "location": "remote"
            }

            if not known_entry:
                logging.info(f"New file detected in Drive: {rel_path}")

            if is_image(filename):
                asset_entry["type"] = "image"
                optimized_path = asset_entry.get("optimized_path")
                optimized_exists = optimized_path and os.path.exists(os.path.join(REPO_PATH, optimized_path))
                if not optimized_exists:
                    dest_optimized = os.path.join(repo_dir, filename)
                    final_optimized_path = optimize_image(drive_path, dest_optimized)

                    if final_optimized_path:
                        rel_opt_path = os.path.relpath(final_optimized_path, REPO_PATH)
                        asset_entry["optimized_path"] = rel_opt_path
                        asset_entry["location"] = "hybrid"
                    else:
                        asset_entry.pop("optimized_path", None)
                        asset_entry["location"] = "remote"
                else:
                    asset_entry["location"] = "hybrid"
            
            elif is_video(filename):
                asset_entry["type"] = "video"
                asset_entry["location"] = "remote"
            
            collected_assets[rel_path] = asset_entry

    # Remove orphaned optimized files when the source asset no longer exists in Drive.
    for rel_path, asset_entry in known_paths.items():
        if rel_path in collected_assets or asset_entry.get('type') == 'markdown':
            continue

        optimized_path = asset_entry.get('optimized_path')
        if not optimized_path:
            continue

        optimized_full_path = os.path.join(REPO_PATH, optimized_path)
        if os.path.exists(optimized_full_path):
            os.remove(optimized_full_path)
            logging.info(f"Removed orphaned optimized file: {optimized_path}")
            
    # 2. Scan Repo (for markdown/local files that are NOT in drive)
    for root, dirs, files in os.walk(REPO_PATH):
        dirs[:] = [
            directory for directory in dirs
            if directory not in {'.git', 'node_modules', '.venv', '__pycache__'}
            and not directory.startswith('.')
        ]

        if '.git' in root or 'node_modules' in root or '.venv' in root:
            continue
             
        rel_dir = os.path.relpath(root, REPO_PATH)
        
        for filename in files:
            if is_markdown(filename):
                # Skip repo-root markdown like README.md (not a vehicle story)
                if rel_dir == '.':
                    continue
                if filename == 'README.md':
                    continue
                rel_path = os.path.join(rel_dir, filename)
                
                # Check if exists in new_assets (it shouldn't came from Drive loop)
                # But check if it was in known_paths?
                
                # Always re-parse metadata for markdown files to capture updates
                full_path = os.path.join(root, filename)
                metadata = parse_frontmatter(full_path)

                asset_entry = copy.deepcopy(collected_assets.get(rel_path) or known_paths.get(rel_path) or {})
                if not asset_entry:
                    logging.info(f"New Markdown detected in Repo: {rel_path}")

                asset_entry.update({
                    "original_path": rel_path,
                    "type": "markdown",
                    "location": "local",
                    "metadata": metadata,
                })
                collected_assets[rel_path] = asset_entry

    # Write Updated Manifest
    manifest = build_nested_manifest(collected_assets, vehicle_info, vehicle_order)
    with open(MANIFEST_FILE, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    logging.info("Sync Complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['migrate', 'sync'], help='migrate: initial move to drive; sync: update from drive')
    args = parser.parse_args()
    
    if args.command == 'migrate':
        migrate()
    else:
        sync()


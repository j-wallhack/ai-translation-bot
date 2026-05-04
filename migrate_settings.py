"""
Migrate old flat JSON settings to the new per-guild format.

Usage:
    python migrate_settings.py <guild_id>

Example:
    python migrate_settings.py 1362049067303043142
"""

import json
import os
import sys

SETTINGS_DIR = "settings"
FILES_TO_MIGRATE = {
    "user_langs.json": "dict",
    "channel_settings.json": "bool",
    "bot_config.json": "config",
}


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"  Saved: {path}")


def is_already_migrated(data, expected_type):
    """Check if data is already in per-guild format."""
    if not data:
        return False
    first_val = next(iter(data.values()))
    if expected_type == "config":
        return isinstance(first_val, dict) and "model_name" in first_val
    if expected_type == "dict":
        return isinstance(first_val, dict) and all(
            isinstance(v, dict) for v in first_val.values()
        )
    if expected_type == "bool":
        return isinstance(first_val, dict) and all(
            isinstance(v, bool) for v in first_val.values()
        )
    return False


def migrate_file(filename, expected_type, guild_id):
    path = os.path.join(SETTINGS_DIR, filename)
    data = load_json(path)

    if data is None:
        print(f"  Skipped: {filename} (file not found)")
        return

    if is_already_migrated(data, expected_type):
        print(f"  Skipped: {filename} (already in per-guild format)")
        return

    # Wrap existing data under the guild ID
    new_data = {guild_id: data}
    save_json(path, new_data)


def main():
    if len(sys.argv) < 2:
        print("Usage: python migrate_settings.py <guild_id>")
        print("\nYou can find your guild (server) ID by enabling Developer Mode")
        print("in Discord, then right-clicking your server name and selecting 'Copy Server ID'.")
        sys.exit(1)

    guild_id = sys.argv[1]

    if not guild_id.isdigit():
        print(f"Error: '{guild_id}' is not a valid guild ID (must be numeric).")
        sys.exit(1)

    print(f"Migrating settings to per-guild format under guild ID: {guild_id}")
    print()

    for filename, expected_type in FILES_TO_MIGRATE.items():
        migrate_file(filename, expected_type, guild_id)

    print("\nMigration complete!")


if __name__ == "__main__":
    main()

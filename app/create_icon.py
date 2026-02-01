#!/usr/bin/env python3
"""Convert SVG icon to PNG for the application."""
import subprocess
import os

# Create PNG icons of various sizes using ImageMagick or rsvg-convert
sizes = [16, 32, 48, 64, 128, 256]

script_dir = os.path.dirname(os.path.abspath(__file__))
svg_path = os.path.join(script_dir, "icon.svg")
icons_dir = os.path.join(script_dir, "icons")

os.makedirs(icons_dir, exist_ok=True)

for size in sizes:
    output = os.path.join(icons_dir, f"icon_{size}.png")
    try:
        # Try rsvg-convert first (better quality)
        subprocess.run([
            "rsvg-convert", "-w", str(size), "-h", str(size),
            svg_path, "-o", output
        ], check=True)
        print(f"Created {output}")
    except FileNotFoundError:
        try:
            # Fallback to ImageMagick
            subprocess.run([
                "convert", "-background", "none",
                "-resize", f"{size}x{size}",
                svg_path, output
            ], check=True)
            print(f"Created {output} (via ImageMagick)")
        except FileNotFoundError:
            print(f"Warning: Neither rsvg-convert nor ImageMagick found. Cannot create {output}")

# Copy 128px icon as main icon
import shutil
main_icon = os.path.join(icons_dir, "icon_128.png")
dest_icon = os.path.join(script_dir, "icon.png")
if os.path.exists(main_icon):
    shutil.copy(main_icon, dest_icon)
    print(f"Copied main icon to {dest_icon}")

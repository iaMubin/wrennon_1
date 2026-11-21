"""
Generate multi-resolution favicons and logo assets from wren-mark.svg
Places favicon.ico, favicon.svg, favicon.png, apple-touch-icon.png,
and wren-mark.svg across all necessary locations in frontend, backend static,
and root directories.
"""

import os
import shutil
import struct
import fitz  # PyMuPDF

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
    repo_root = os.path.dirname(root_dir)  # workspace root
    
    svg_source = os.path.join(repo_root, "frontend", "agent", "images", "wren-mark.svg")
    if not os.path.exists(svg_source):
        svg_source = os.path.join(root_dir, "app", "static", "agent", "images", "wren-mark.svg")
    
    print(f"Reading SVG from: {svg_source}")
    with open(svg_source, "r", encoding="utf-8") as f:
        svg_content = f.read()
    
    # 1. Rasterize PNGs
    doc = fitz.open(svg_source)
    png_renders = {}
    for size in [16, 32, 48, 64, 180, 192, 512]:
        scale = size / 32.0
        mat = fitz.Matrix(scale, scale)
        pix = doc[0].get_pixmap(matrix=mat, alpha=True)
        png_renders[size] = pix.tobytes(output="png")
        print(f"Generated {size}x{size} PNG ({len(png_renders[size])} bytes)")
    
    # 2. Build multi-resolution ICO (16, 32, 48)
    ico_sizes = [16, 32, 48]
    header = struct.pack("<HHH", 0, 1, len(ico_sizes))
    offset = 6 + 16 * len(ico_sizes)
    dir_entries = bytearray()
    payload = bytearray()
    
    for size in ico_sizes:
        png = png_renders[size]
        w = 0 if size == 256 else size
        h = 0 if size == 256 else size
        entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset)
        dir_entries.extend(entry)
        payload.extend(png)
        offset += len(png)
    
    ico_bytes = header + dir_entries + payload
    print(f"Generated multi-resolution ICO ({len(ico_bytes)} bytes)")
    
    # 3. Target directories
    target_dirs = [
        os.path.join(repo_root, "frontend"),
        os.path.join(repo_root, "frontend", "agent"),
        os.path.join(root_dir, "app", "static"),
        os.path.join(root_dir, "app", "static", "agent"),
        repo_root,
    ]
    
    for d in target_dirs:
        os.makedirs(d, exist_ok=True)
        # favicon.ico
        with open(os.path.join(d, "favicon.ico"), "wb") as f:
            f.write(ico_bytes)
        # favicon.svg
        with open(os.path.join(d, "favicon.svg"), "w", encoding="utf-8") as f:
            f.write(svg_content)
        # favicon-32x32.png
        with open(os.path.join(d, "favicon-32x32.png"), "wb") as f:
            f.write(png_renders[32])
        # favicon-16x16.png
        with open(os.path.join(d, "favicon-16x16.png"), "wb") as f:
            f.write(png_renders[16])
        # apple-touch-icon.png (180x180)
        with open(os.path.join(d, "apple-touch-icon.png"), "wb") as f:
            f.write(png_renders[180])
        # favicon.png / icon-192.png
        with open(os.path.join(d, "favicon.png"), "wb") as f:
            f.write(png_renders[192])
        with open(os.path.join(d, "icon-192.png"), "wb") as f:
            f.write(png_renders[192])
        with open(os.path.join(d, "icon-512.png"), "wb") as f:
            f.write(png_renders[512])
        print(f"Updated favicons in {d}")
        
    # 4. Copy wren-mark.svg and wren-mark.png to all images directories
    image_dirs = [
        os.path.join(repo_root, "frontend", "images"),
        os.path.join(repo_root, "frontend", "agent", "images"),
        os.path.join(root_dir, "app", "static", "images"),
        os.path.join(root_dir, "app", "static", "agent", "images"),
        os.path.join(repo_root, "images"),
    ]
    
    for img_dir in image_dirs:
        os.makedirs(img_dir, exist_ok=True)
        with open(os.path.join(img_dir, "wren-mark.svg"), "w", encoding="utf-8") as f:
            f.write(svg_content)
        with open(os.path.join(img_dir, "wren-mark.png"), "wb") as f:
            f.write(png_renders[192])
        print(f"Placed wren-mark.svg and wren-mark.png in {img_dir}")

    print("Favicon & logo asset generation complete!")

if __name__ == "__main__":
    main()

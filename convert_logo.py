"""
Convert luminis_logo.png to TGA and ICO formats for WoW addon and Windows executable
"""
from PIL import Image
import os

# Open the PNG logo
png_path = "luminis_logo.png"
print(f"Opening {png_path}...")
img = Image.open(png_path)
print(f"Original size: {img.size}")

# Ensure the WoW addon assets directory exists
wow_assets_dir = "wow_addon/LuminisbotEvents/assets"
os.makedirs(wow_assets_dir, exist_ok=True)

# Convert to TGA for WoW addon (keep original size for best quality)
tga_path = os.path.join(wow_assets_dir, "luminis_logo.tga")
print(f"\nConverting to TGA: {tga_path}")
img.save(tga_path, format="TGA")
print(f"✓ TGA created successfully")

# Convert to ICO for Windows executable (multiple sizes for different contexts)
ico_path = "companion_app/luminis_logo.ico"
print(f"\nConverting to ICO: {ico_path}")

# Create ICO with multiple sizes (16x16, 32x32, 48x48, 64x64, 128x128, 256x256)
# Windows will automatically pick the best size for different contexts
icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(ico_path, format="ICO", sizes=icon_sizes)
print(f"✓ ICO created successfully with sizes: {icon_sizes}")

print("\n✓ All conversions complete!")
print(f"  - TGA for WoW addon: {tga_path}")
print(f"  - ICO for Windows exe: {ico_path}")

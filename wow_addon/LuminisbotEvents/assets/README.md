# Addon Assets

## Logo

Place the Luminis logo as `luminis_logo.tga` in this folder.

### Requirements:
- **Format:** TGA (Targa) - WoW's preferred texture format
- **Size:** 256x128 pixels (power of 2 dimensions)
- **Color Mode:** RGB or RGBA
- **Background:** Transparent alpha channel recommended

### Convert from PNG:
You can use tools like:
- Photoshop: File → Save As → Targa (.tga)
- GIMP: File → Export As → Targa (.tga)
- ImageMagick: `convert luminis_logo.png -resize 256x128 luminis_logo.tga`

### Usage:
The addon will automatically load the texture and display it in the header if present.

Path referenced in code: `Interface\\AddOns\\LuminisbotEvents\\assets\\luminis_logo`

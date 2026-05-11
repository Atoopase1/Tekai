from PIL import Image, ImageDraw
import math

def process_logo():
    # Load image and convert to RGBA
    img = Image.open('logo.jpeg').convert('RGBA')
    width, height = img.size

    # 1. Circle Crop
    # Determine the radius and center
    center_x, center_y = width / 2, height / 2
    radius = min(center_x, center_y) - 5
    
    # Create mask for the circle
    mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((center_x - radius, center_y - radius, center_x + radius, center_y + radius), fill=255)

    # Apply the mask to the image's alpha channel
    img.putalpha(mask)

    # 2. Fill the "AI" letters with sea blue (#006994)
    # The letters are white. 
    # We will iterate through pixels, and if a pixel is white-ish, and it's surrounded by non-white boundaries, we fill it.
    # A simple approach is just to flood fill the specific coordinates inside the 'A' and 'i'.
    # Since we don't know the exact coordinates, we can do a flood fill from the center assuming it's inside the 'A'.
    # But a more robust way is to find all pixels that are very bright (white) and NOT touching the border.
    
    pixels = img.load()
    
    # Create a boolean mask of "white" pixels
    is_white = [[False] * height for _ in range(width)]
    for x in range(width):
        for y in range(height):
            r, g, b, a = pixels[x, y]
            if a > 0 and r > 220 and g > 220 and b > 220:
                is_white[x][y] = True

    # Flood fill from the 4 corners to mark the "outside white"
    outside = [[False] * height for _ in range(width)]
    stack = [(0, 0), (width-1, 0), (0, height-1), (width-1, height-1)]
    
    while stack:
        cx, cy = stack.pop()
        if 0 <= cx < width and 0 <= cy < height:
            if is_white[cx][cy] and not outside[cx][cy]:
                outside[cx][cy] = True
                stack.append((cx+1, cy))
                stack.append((cx-1, cy))
                stack.append((cx, cy+1))
                stack.append((cx, cy-1))

    # Now color all "inside white" pixels sea blue
    sea_blue = (0, 105, 148, 255)
    for x in range(width):
        for y in range(height):
            if is_white[x][y] and not outside[x][y]:
                # It's inside the letters or shapes!
                # Blend the sea blue based on original brightness to preserve anti-aliasing slightly
                r, g, b, a = pixels[x, y]
                brightness = (r + g + b) / (3.0 * 255.0)
                # Apply sea blue
                pixels[x, y] = (
                    int(sea_blue[0] * brightness), 
                    int(sea_blue[1] * brightness), 
                    int(sea_blue[2] * brightness), 
                    a
                )

    # Crop to the circle bounds
    bbox = (int(center_x - radius), int(center_y - radius), int(center_x + radius), int(center_y + radius))
    cropped = img.crop(bbox)

    # Save
    cropped.save('static/logo.png', 'PNG')
    # Also overwrite the root one
    cropped.save('logo.jpeg', 'PNG') # saving as PNG but keeping extension or replacing it

if __name__ == "__main__":
    process_logo()

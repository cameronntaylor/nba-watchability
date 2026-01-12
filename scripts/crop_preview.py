from PIL import Image

img = Image.open("output/full.png")
width, height = img.size

LEFT_PAD = 50
TOP_PAD = 300     # 👈 cut off header / tabs
RIGHT_PAD = 700      # 👈 cut off right column
BOTTOM_PAD = 0      # optional

crop_box = (
        LEFT_PAD,
        TOP_PAD,
        width - RIGHT_PAD,
        height - BOTTOM_PAD,
    )

cropped = img.crop(crop_box)
cropped.show()  # 👈 opens instantly on your machine
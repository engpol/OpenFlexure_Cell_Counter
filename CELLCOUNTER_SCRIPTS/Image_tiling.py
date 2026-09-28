import os
from PIL import Image

captured_image_dir = "/home/openflexure/Applications/Cell_Counter/captured_images" # Filepaths of the 4 TIFF images

def tile_4_tiff(captured_image_dir):
    image_dir = captured_image_dir ## Define dir where images from scope are saved
    image_files = [os.path.join(image_dir,file) for file in os.listdir(image_dir) if file.lower().endswith('.tiff')] # Open the images
    images = [Image.open(image) for image in image_files]
    # Ensure all images are the same size (if needed, resize here)
    image_width, image_height = images[0].size
    # Create a new blank image to combine them
    combined_width = 2 * image_width
    combined_height = 2 * image_height
    combined_image = Image.new("RGB", (combined_width, combined_height))
    # Paste the images into the blank canvas
    combined_image.paste(images[0], (0, 0))  # Top-left
    combined_image.paste(images[1], (image_width, 0))  # Top-right
    combined_image.paste(images[2], (0, image_height))  # Bottom-left
    combined_image.paste(images[3], (image_width, image_height))  # Bottom-right
    # Save the final combined image
    combined_image.save("/home/openflexure/Applications/Cell_Counter/chosen_image/chosen_image.tiff", compression="tiff_deflate")
    print("Combined image saved as 'chosen_image.tiff'")

if __name__ == "__main__":
    tile_4_tiff(captured_image_dir)
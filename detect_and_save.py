import sys
from predict.detectStoma import mainImage

def detect_stomata_and_save(image_path):
    """
    Detects stomata in the given image and saves them in a PASCAL VOC file
    in the same directory.
    """
    # Call the detection function from the detectStoma module
    mainImage(image_path)
    
    print(f"Detections for {image_path} have been saved in the same directory with XML format.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python detect_and_save.py <path_to_image>")
        sys.exit(1)

    image_path = sys.argv[1]
    detect_stomata_and_save(image_path)


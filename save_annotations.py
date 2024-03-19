import cv2
import xml.etree.ElementTree as ET
import argparse
import os

def visualize_annotations(image_path):
    # Derive XML path from image path
    xml_path = os.path.splitext(image_path)[0] + '.xml'
    
    # Generate the annotated image save path
    save_path = os.path.splitext(image_path)[0] + '_annotated.png'

    # Load the image
    img = cv2.imread(image_path)

    # Parse the XML file
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Draw each bounding box
    for obj in root.findall('object'):
        bbox = obj.find('bndbox')
        x1 = int(bbox.find('xmin').text)
        y1 = int(bbox.find('ymin').text)
        x2 = int(bbox.find('xmax').text)
        y2 = int(bbox.find('ymax').text)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
    
    # Save the image with annotations
    cv2.imwrite(save_path, img)
    print(f"Annotated image saved as: {save_path}")

def main():
    # Create argument parser
    parser = argparse.ArgumentParser(description="Visualize PASCAL VOC annotations on an image and save it.")
    parser.add_argument("image_path", help="Path to the image file")

    # Parse arguments
    args = parser.parse_args()

    # Visualize annotations and save the result
    visualize_annotations(args.image_path)

if __name__ == "__main__":
    main()

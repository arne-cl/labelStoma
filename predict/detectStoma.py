import cv2 as cv #s
import numpy as np
import xml.etree.ElementTree as ET
import xml.etree.ElementTree as ET
from xml.dom import minidom
from imutils import paths
import sys
import os
import urllib.request
from tqdm import tqdm
import shutil


confThreshold = 0.25  #Confidence threshold
nmsThreshold = 0.45   #Non-maximum suppression threshold
#inpWidth = 416       #Width of network's input image
#inpHeight = 416      #Height of network's input image


def getOutputsNames(net):
    """Get the names of the output layers."""
    # Get the names of all the layers in the network
    layersNames = net.getLayerNames()
    # Get the names of the output layers, i.e., the layers with unconnected outputs
    outLayers = net.getUnconnectedOutLayers()
    
    # Check if the function returns a numpy array or a list (depends on OpenCV version)
    if isinstance(outLayers, np.ndarray):
        # If it's a numpy array (common in newer OpenCV versions), flatten it
        outLayers = outLayers.flatten()
    else:
        # Otherwise (in older versions), it's a list of lists, so extract the first element
        outLayers = [i[0] for i in outLayers]
    
    return [layersNames[i - 1] for i in outLayers]


def postprocess(frame, outs, conf):
    """Remove the bounding boxes with low confidence using non-maxima suppression."""
    frameHeight = frame.shape[0]
    frameWidth = frame.shape[1]

    classIds = []
    confidences = []
    boxes = []
    for out in outs:
        for detection in out:
            scores = detection[5:]
            classId = np.argmax(scores)
            confidence = scores[classId]
            if confidence > conf:
                center_x = int(detection[0] * frameWidth)
                center_y = int(detection[1] * frameHeight)
                width = int(detection[2] * frameWidth)
                height = int(detection[3] * frameHeight)
                left = int(center_x - width / 2)
                top = int(center_y - height / 2)
                classIds.append(classId)
                confidences.append(float(confidence))
                boxes.append([left, top, width, height])

    indices = cv.dnn.NMSBoxes(boxes, confidences, conf, nmsThreshold)

    # Check the type of indices and adapt accordingly
    if isinstance(indices, list):  # For older OpenCV versions
        indices = [i for i in indices]
    elif isinstance(indices, np.ndarray) and indices.ndim == 2:  # Newer OpenCV versions
        indices = indices.flatten()  # Flatten to 1D array if it's 2D

    newBoxes = []
    newConfi = []
    for i in indices:
        newConfi.append(confidences[i])
        newBoxes.append(boxes[i])

    return newBoxes, newConfi


#Load names of classes
dirPath =os.path.dirname(os.path.realpath(__file__))
classesFile = dirPath + "/../fichs/vocEstomas.names";

classes = None
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')



class DownloadProgressBar(tqdm):
    def update_to(self, b=1, bsize=1, tsize=None):
        if tsize is not None:
            self.total = tsize
        self.update(b * bsize - self.n)


# Give the configuration and weight files for the model and
# load the network using them.
modelConfiguration = dirPath + "/../fichs/yolov3Estomas.cfg";
modelWeights = dirPath + "/../fichs/yolov3Stomata.weights";
url = "https://www.dropbox.com/s/fce0bsyl12enh4e/yolov3Stomata.weights?dl=1"
if  not os.path.exists(modelWeights):
    with DownloadProgressBar(unit='B', unit_scale=True,
                             miniters=1, desc=url.split('/')[-1]) as t:
        urllib.request.urlretrieve(url, filename=modelWeights, reporthook=t.update_to)




def prettify(elem):
    """Return a pretty-printed XML string for the Element.
    """
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def generateXML(filename,outputPath,w,h,d,boxes,confidences):
    top = ET.Element('annotation')
    childFolder = ET.SubElement(top, 'folder')
    childFolder.text = 'images'
    childFilename = ET.SubElement(top, 'filename')
    childFilename.text = filename[0:filename.rfind(".")]
    childPath = ET.SubElement(top, 'path')
    childPath.text = outputPath + "/" + filename
    childSource = ET.SubElement(top, 'source')
    childDatabase = ET.SubElement(childSource, 'database')
    childDatabase.text = 'Unknown'
    childSize = ET.SubElement(top, 'size')
    childWidth = ET.SubElement(childSize, 'width')
    childWidth.text = str(w)
    childHeight = ET.SubElement(childSize, 'height')
    childHeight.text = str(h)
    childDepth = ET.SubElement(childSize, 'depth')
    childDepth.text = str(d)
    childSegmented = ET.SubElement(top, 'segmented')
    childSegmented.text = str(0)
    for box, con in zip(boxes,confidences):
        category = 'stoma'
        (x,y,wb,hb) = box
        childObject = ET.SubElement(top, 'object')
        childName = ET.SubElement(childObject, 'name')
        childName.text = category
        childPose = ET.SubElement(childObject, 'pose')
        childPose.text = 'Unspecified'
        childTruncated = ET.SubElement(childObject, 'truncated')
        childTruncated.text = '0'
        childDifficult = ET.SubElement(childObject, 'difficult')
        childDifficult.text = '0'
        childConfidence = ET.SubElement(childObject, 'confidence')
        childConfidence.text = str(con)
        childBndBox = ET.SubElement(childObject, 'bndbox')
        childXmin = ET.SubElement(childBndBox, 'xmin')
        childXmin.text = str(x)
        childYmin = ET.SubElement(childBndBox, 'ymin')
        childYmin.text = str(y)
        childXmax = ET.SubElement(childBndBox, 'xmax')
        childXmax.text = str(x+wb)
        childYmax = ET.SubElement(childBndBox, 'ymax')
        childYmax.text = str(y+hb)
    return prettify(top)


def generateXMLFromImage(imagePath, conf):
    #net = cv.dnn.readNetFromDarknet(modelConfiguration, modelWeights)
    net = cv.dnn.readNet(modelWeights, modelConfiguration)
    net.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv.dnn.DNN_TARGET_CPU)
    #im = cv.VideoCapture(imagePath)
    #hasFrame, frame = im.read()
    frame = cv.imread(str(imagePath))
    # Sets the input to the network
    palabra1 = "width"
    palabra2 = "height"
    with open(modelConfiguration) as f:
        for linea in f:
            if palabra1 in linea:
                partes =linea.split('=')
                inpWidth = int(partes[1])
            elif palabra2 in linea:
                partes =linea.split('=')
                inpHeight = int(partes[1])

    blob = cv.dnn.blobFromImage(frame, 1 / 255, (1024, 1024), [0, 0, 0], 1, crop=False)
    #blob = cv.dnn.blobFromImage(frame, 1 / 255, ("600", "600"), [0, 0, 0], 1, crop=False)
    net.setInput(blob)
    # Runs the forward pass to get output of the output layers
    outs = net.forward(getOutputsNames(net))
    boxes, confidences = postprocess(frame, outs, conf)
    wI, hI, d = frame.shape
    # Remove the bounding boxes with low confidence
    #boxes = postprocess(frame, outs)
    #wI, hI, d = frame.shape
    file = open(imagePath[0:imagePath.rfind(".")] + ".xml", "w")
    file.write(generateXML(imagePath[0:imagePath.rfind(".")], "", wI, hI, d, boxes, confidences))
    file.close()



def mainImage(imagePath):
    # Leemos el parametro pasado por linea de comandos
    #arg1 = sys.argv[1]
    #arg2 = sys.argv[2]
    #arg3 = sys.argv[3]
    #print(prueba.genera_vector_aleatorio(arg1,arg2,arg3))
    generateXMLFromImage(imagePath,confThreshold)

def mainDataset(imagesPath):
    images = list(paths.list_files(imagesPath, validExts=(".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")))
    for image in images:
        image = image.replace("\\ ", " ")
        generateXMLFromImage(image,confThreshold)

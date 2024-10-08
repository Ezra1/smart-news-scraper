"""image_processor.py: Integrates YOLO for detecting specific objects in the article images.
Loads images and runs them through the YOLO model.
Outputs detected objects with confidence scores."""

import cv2
from ultralytics import YOLO
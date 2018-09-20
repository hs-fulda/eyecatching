import subprocess
import os
import sys
import shutil
import imagehash
import cv2
import pandas
import time
import numpy as np
from PIL import Image
from urllib.parse import urlparse
from eyecatchingutil import MetaImage
from eyecatchingutil import FirefoxScreenshot
from eyecatchingutil import ChromeScreenshot
from eyecatchingutil import Coordinates
from eyecatchingutil import ImageComparator
from cv2 import VideoWriter, VideoWriter_fourcc, imread, resize

class Controller:

    output_id = "_"
    block_size = 20
    width = 1280
    threshold = 8
    algorithm = "ahash"
    ref = None
    com = None
    ref_screenshot = None
    com_screenshot = None
    url = None

    def __init__(self):
        # used for recursive operations
        self._rec_count = 0
        self._rec_total_diff = 0

    def compare_recursive(self, patch_coords):
        """
        Compares two image slice with given coordinates
        """
        x1, y1, x2, y2 = patch_coords
        ref_img_slice = self.ref.image.crop(patch_coords)
        com_img_slice = self.com.image.crop(patch_coords)

        ic = ImageComparator(ref_img_slice, com_img_slice)
        diff = ic.hamming_diff(self.algorithm)

        if diff <= self.threshold and ic.is_similar_by_color() == False:
            blended = self.blend_image_recursive(self.ref.image, patch_coords, diff)
            self.ref.image.paste(blended, (x1, y1))
            # Increase dissimilar portion count
            self._rec_count += 1
            self._rec_total_diff += diff
            return
        else:
            # go inside and compare again
            self.divide_recursive(patch_coords, diff)
            return

    def divide_recursive(self, initial_coords, diff):
        (x1, y1, x2, y2) = initial_coords
        coords = Coordinates(x1, y1, x2, y2)

        # return and save if image is less than 8px
        # TODO: add diff != 0 and test
        if coords.width <= self.block_size or coords.height <= self.block_size:
            blended = self.blend_image_recursive(self.ref.image, initial_coords, diff)
            self.ref.image.paste(blended, (x1, y1))
            self._rec_count += 1
            self._rec_total_diff += diff
            return
        # Divide the image with larger side
        else:
            self.compare_recursive(coords.first_half())
            self.compare_recursive(coords.second_half())
            return

    def blend_image_recursive(self, image_obj, coords, diff):
        patch = image_obj.crop(coords)
        opacity = (100 * diff / 64) / 100 if diff != 0 else 0
        img1 = patch.convert("RGB")
        img2 = Image.new("RGB", patch.size, "salmon")
        blended = Image.blend(img1, img2, opacity)
        return blended

    def save_output(self, image_obj:Image.Image, methodname:str):
        method = methodname[:3]
        output_name = "output_{0}_{1}_{2}_{3}_{4}.{5}".format(
            method,
            self.output_id,
            self.ref.name,
            self.com.name,
            self.algorithm,
            self.ref.ext
        )
        image_obj.save(output_name)
        print("Done: \tOutput saved as: {0}".format(output_name))

    def compare_linear(self):
        """
        Compare two images block by block
        """
        start_time = time.time()

        counter = 0
        counter_problem = 0
        total_diff = 0
        edge = int(self.block_size)

        for x in range(0, self.com.image.width, edge):
            for y in range(0, self.com.image.height, edge):
                coords = (x, y, x + edge, y + edge)
                ref_tile = self.ref.get_cropped(coords)
                com_tile = self.com.get_cropped(coords)
                # compare with ref tile
                ic = ImageComparator(ref_tile, com_tile)
                hash_diff =  ic.hash_diff(self.algorithm)
                hash_diff_percent = ic.hash_diff_percent(self.algorithm)
                # get an opacity value between 0 - 1
                opacity = hash_diff_percent / 100

                if hash_diff >= self.threshold:
                    blended = self.blend_image(ref_tile, opacity)
                    self.ref.image.paste(blended, coords)
                    counter_problem += 1

                del ref_tile, com_tile
                total_diff += hash_diff_percent
                counter += 1

        stop_time = time.time()
        self.save_output(self.ref.image, "linear")

        print("Done: \tTotal blocks compared: {0}.".format(counter))
        print("Done: \tNumber of blocks with dissimilarity: {0}".format(counter_problem))
        print("Done: \tAverage dissimilarity {0:.2f}%.".format(round(total_diff / counter, 2)))
        print("Done: \tExecution time: {0:.4f} seconds".format(stop_time - start_time))

        return self.ref.image

    def blend_image(self, image_obj, opacity, color = "salmon"):
        img1 = image_obj.convert("RGB")
        img2 = Image.new("RGB", img1.size, color)
        return Image.blend(img1, img2, opacity)

    def get_screenshot(self, url):
        self.ref_screenshot.width = self.width
        self.com_screenshot.width = self.width
        self.ref_screenshot.take_shot(url)
        self.com_screenshot.take_shot(url)

    def set_images(self, ref_imagename = None, com_imagename = None):
        if ref_imagename is None:
            self.ref = MetaImage(self.ref_screenshot.imagename)
        else:
            self.ref = MetaImage(ref_imagename)

        if com_imagename is None:
            self.com = MetaImage(self.com_screenshot.imagename)
        else:
            self.com = MetaImage(com_imagename)

    def normalize_images(self, image1, image2):
        """
        Make 2 images equal height by adding white background to the smaller image
        """
        img1 = MetaImage(image1)
        img2 = MetaImage(image2)

        print("Info: \t{0} image size: {1}x{2}".format(image1, img1.width, img1.height))
        print("Info: \t{0} image size: {1}x{2}".format(image2, img2.width, img2.height))
        print("Work:\tMaking both image size equal (as larger image)")

        if img1.size == img2.size:
            print("Info: \tImage sizes are already equal")
            return

        bigger_ht = img1.height if (img1.height >= img2.height) else img2.height
        bigger_wd = img1.width if (img1.width >= img2.width) else img2.width

        newimg = Image.new("RGB", (bigger_wd, bigger_ht), "white")
        # which one is smaller
        if img1.size == (bigger_wd, bigger_ht):
            newimg.paste(img2.image)
            newimg.save(image2)
        else:
            newimg.paste(img1.image)
            newimg.save(image1)

        print("Done: \t{0} and {1} both are now {2}x{3} pixels.".format(
            image1, image2, bigger_wd, bigger_ht
        ))

    def detect_shift(self, image1, image2):
        """
        Detect shift of objects between two images
        """
        print("Work:\tStarting shift detection process")
        fourcc = VideoWriter_fourcc(*"XVID")
        img1 = imread(image1)
        img2 = imread(image2)
        size = img1.shape[1], img1.shape[0]
        output_vid = VideoWriter(
            "output_vid.avi",
            fourcc,
            float(40),
            size,
            True
        )
        # make a white image for comparing
        img_white = np.zeros((size[1], size[0], 3), np.uint8)
        img_white.fill(255)

        start_time = time.time()

        # add frames to output video
        output_vid.write(img_white)
        output_vid.write(img1)
        output_vid.write(img2)
        output_vid.write(img1)
        
        output_vid.release()

        first_frame = None

        video = cv2.VideoCapture("output_vid.avi")
        count = 1
        objects_ref = []
        objects_com = []

        def draw_rectangles(frame, is_ref_image):
            color_red = (0, 0, 255)
            color_green = (0, 255, 0)
            if is_ref_image:
                for i in objects_ref:
                    (x, y, w, h) = i
                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + w, y + h),
                        color_red,
                        2               # strokes
                    )
            else:
                for i in objects_com:
                    (x, y, w, h) = i
                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + w, y + h),
                        color_green,
                        2               # strokes
                    )
            return frame

        while True:
            is_being_read, frame = video.read()
            is_present = -1

            if is_being_read is True:
                current_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                break

            # remove blur and noise 
            # kernel size (21, 21), std deviation = 0
            current_frame = cv2.GaussianBlur(current_frame, (21, 21), 0)

            if first_frame is None:
                first_frame = current_frame
                continue

            # get the differences between current and ref frame
            delta_frame = cv2.absdiff(first_frame, current_frame)
            # convert background above threshold to white
            threshold_frame = cv2.threshold(delta_frame, 30, 255, cv2.THRESH_BINARY)[1]
            # smoothen to remove sharp edges
            # this frame now holds closed shapes with objects against background
            threshold_frame = cv2.dilate(threshold_frame, None, iterations = 2)

            (_, contours, _) = cv2.findContours(
                threshold_frame.copy(),
                cv2.RETR_EXTERNAL,          # ignore inside contours
                cv2.CHAIN_APPROX_SIMPLE     # method for locating contours
            )

            # bigger for big objects, smaller for small
            # 100 = 10 x 10px
            shape_size_factor = 100
            for contour in contours:
                if cv2.contourArea(contour) < shape_size_factor:
                    continue
                
                is_present = 1
                # get corresponding bounding for the detected contour
                (x, y, w, h) = cv2.boundingRect(contour)
                if count == 1:
                    objects_ref.append((x, y, w, h))
                elif count == 2:
                    objects_com.append((x, y, w, h))
            
            if count == 1:
                frame = draw_rectangles(frame, True)
                output_filename = "output_struct_{0}_{1}.{2}".format(
                    self.output_id,
                    self.ref.name,
                    self.ref.ext
                )
            elif count == 2:
                frame = draw_rectangles(frame, False)
                output_filename = "output_struct_{0}_{1}.{2}".format(
                    self.output_id,
                    self.com.name,
                    self.ref.ext
                )
            elif count == 3:
                # green on top
                frame = draw_rectangles(frame, True)
                frame = draw_rectangles(frame, False)
                output_filename = "output_shift_{0}_{1}_{2}.{3}".format(
                    self.output_id,
                    self.ref.name,
                    self.com.name,
                    self.ref.ext
                )

            cv2.imwrite(output_filename, frame)
            count += 1

        cv2.destroyAllWindows()
        video.release()
        stop_time = time.time()

        print("Done:\tShift detection process completed")
        print("Done:\tExecution time: {0:.4f} seconds".format(stop_time - start_time))


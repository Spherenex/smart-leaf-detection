import cv2
from threading import Thread
import time

class VideoStream:
    def __init__(self, src):
        # ✅ Use FFMPEG backend for RTSP
        self.stream = cv2.VideoCapture(src, cv2.CAP_FFMPEG)

        if not self.stream.isOpened():
            raise RuntimeError(f"❌ Unable to open video source: {src}")

        # read first frame
        self.ret, self.frame = self.stream.read()
        self.stopped = False
        self.thread = Thread(target=self.update, args=())
        self.thread.daemon = True  # ensures thread exits when main program ends

    def start(self):
        """Start the thread to read frames."""
        self.thread.start()
        return self

    def update(self):
        """Continuously update frames in a separate thread."""
        while not self.stopped:
            if not self.stream.isOpened():
                time.sleep(0.1)
                continue
            self.ret, self.frame = self.stream.read()
            if not self.ret:
                # If frame not received, wait a little to avoid busy loop
                time.sleep(0.05)

    def read(self):
        """Return the most recent frame."""
        return self.ret, self.frame

    def stop(self):
        """Stop the thread and release the stream."""
        self.stopped = True
        if self.thread.is_alive():
            self.thread.join()
        if self.stream.isOpened():
            self.stream.release()

import logging
import socket
import struct
import base64
from io import BytesIO
from PIL import Image

logger = logging.getLogger(__name__)

# Stripe sizes (number of dots in a vertical stripe) per tape size
# These match the P950NW values; the P900W uses the same 360 dpi print head
STRIPE_SIZES = {
    "3.5mm": 24,
    "6mm": 48,
    "9mm": 80,
    "12mm": 112,
    "18mm": 408,
    "24mm": 468,
    "36mm": 536,
}

VALID_TAPE_SIZES = list(STRIPE_SIZES.keys())


class PTouchPrinterService:
    """Printer service for Brother P-touch series (PT-P900W, PT-P950NW, etc.)"""

    def __init__(self, model: str, printer_address: str, **kwargs):
        self.model = model
        self.printer_address = printer_address

    def _parse_address(self):
        """Parse printer address into (host, port) tuple"""
        addr = self.printer_address
        if addr.startswith("tcp://"):
            addr = addr[6:]
        if ":" in addr:
            host, port_str = addr.rsplit(":", 1)
            return host, int(port_str)
        return addr, 9100

    def is_online(self, timeout: float = 2.0) -> bool:
        """Check if the printer is reachable"""
        try:
            host, port = self._parse_address()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"Printer connectivity check failed for {self.printer_address}: {e}")
            return False

    def decode_base64_image(self, base64_string: str) -> Image.Image:
        """Decode a base64 string into a PIL Image"""
        try:
            if "," in base64_string:
                base64_string = base64_string.split(",", 1)[1]
            image_data = base64.b64decode(base64_string)
            image = Image.open(BytesIO(image_data))
            if image.mode not in ("L", "RGB"):
                image = image.convert("RGB")
            return image
        except Exception as e:
            logger.error(f"Failed to decode base64 image: {e}")
            raise

    def _prepare_image(self, image: Image.Image) -> Image.Image:
        """Convert image to RGB, handling RGBA transparency"""
        if image.mode == "P":
            image = image.convert("RGBA")
        if image.mode == "RGBA":
            new_img = Image.new("RGB", image.size, (255, 255, 255))
            new_img.paste(image, mask=image.split()[3])
            image = new_img
        if image.mode == "L":
            image = image.convert("RGB")
        return image

    def _render_raster(self, image: Image.Image, tape_size: str, threshold: int = 70, copies: int = 1) -> bytes:
        """
        Render image to Brother P-touch raster format.

        Adapted from the rasterprynt library's render() function.
        The protocol is documented in Brother's Raster Command Reference.
        """
        stripe_size = STRIPE_SIZES.get(tape_size)
        if stripe_size is None:
            raise ValueError(f"Unsupported tape size: {tape_size}. Valid sizes: {VALID_TAPE_SIZES}")

        stripe_count = stripe_size // 8

        image = self._prepare_image(image)
        img_bytes = image.load()

        top_margin = 3
        bottom_margin = 3

        data = bytearray()

        # Initialize printer
        data.extend(b"\x00" * 200)  # Sync/clear buffer
        data.extend(b"\x1b@")  # ESC @ - Initialize
        data.extend(b"\x1bia\x01")  # Switch to raster mode
        data.extend(b"\x1biM\x40")  # Various mode settings: auto cut enabled
        data.extend(b"\x1biK\x08")  # Half cut enabled
        data.extend(b"\x1bid\x00\x00")  # Margin = 0

        # Threshold for black/white conversion (0-255)
        bw_threshold = max(0, min(255, 255 - threshold * 255 // 100)) if threshold <= 100 else threshold

        first = True
        for copy_num in range(copies):
            if first:
                first = False
            else:
                data.extend(b"\x0c")  # Form feed between copies

            raster_number = image.width + top_margin + bottom_margin

            # Print information command
            data.extend(b"\x1biz")  # ESC i z
            data.extend(b"\xc0")  # PI_RECOVER | PI_QUALITY
            data.extend(b"\x00")  # Media type: not set
            data.extend(b"\x00")  # Media width: unspecified
            data.extend(b"\x00")  # Media length: not set
            data.extend(struct.pack("<I", raster_number))  # Raster number
            data.extend(b"\x00" if copy_num == 0 else b"\x01")  # Starting page
            data.extend(b"\x00")  # Reserved

            data.extend(b"M\x00")  # Compression mode: none

            # Top margin (empty raster lines)
            data.extend(b"Z" * top_margin)

            # Render image data column by column
            for x in range(image.width):
                y_offset = stripe_size - image.height

                row = bytearray()
                for stripe_idx in range(stripe_count):
                    bits = 0
                    for bit_index in range(8):
                        y = stripe_idx * 8 + bit_index - y_offset
                        if 0 <= x < image.width and 0 <= y < image.height:
                            color = img_bytes[(x, y)]
                            if isinstance(color, int):
                                px = color
                            else:
                                px = sum(color) // 3
                            if px <= bw_threshold:
                                bits |= 1 << (7 - bit_index)
                    row.append(bits)

                data.extend(b"G" + struct.pack("<H", len(row)))
                data.extend(row)

            # Bottom margin
            data.extend(b"Z" * bottom_margin)

        # Print command
        data.extend(b"\x1a")

        return bytes(data)

    def print_label(
        self,
        image_data: str,
        label_size: str,
        threshold: int = 70,
        rotate: str = "auto",
        copies: int = 1,
    ) -> bool:
        """
        Print a label on a P-touch printer.

        Args:
            image_data: Base64 encoded image data
            label_size: Tape size (e.g., '18mm', '24mm', '36mm')
            threshold: Threshold for black/white conversion (0-255 or 0-100)
            rotate: Rotation setting ('auto', '0', '90', '180', '270')
            copies: Number of copies to print

        Returns:
            bool: True if successful
        """
        try:
            if copies < 1:
                raise ValueError("Number of copies must be at least 1")
            if copies > 100:
                raise ValueError("Number of copies cannot exceed 100")

            image = self.decode_base64_image(image_data)

            tape_stripe = STRIPE_SIZES.get(label_size, 408)

            # Handle rotation
            if rotate == "auto":
                # For P-touch tape, the image height should match the tape's printable area
                # Rotate if the image is taller than wide and would fit better rotated
                if image.height > image.width and image.height > tape_stripe:
                    image = image.rotate(90, expand=True)
            elif rotate and rotate != "0":
                image = image.rotate(int(rotate), expand=True)

            # Scale image height to match tape width (fill the tape)
            if image.height != tape_stripe:
                ratio = tape_stripe / image.height
                new_width = max(1, int(image.width * ratio))
                image = image.resize((new_width, tape_stripe), Image.LANCZOS)

            # Render to raster format
            raster_data = self._render_raster(image, label_size, threshold, copies)

            # Send to printer
            host, port = self._parse_address()
            logger.info(f"Printing {copies} copies to {host}:{port} (tape: {label_size})")

            sock = socket.create_connection((host, port), timeout=10)
            sock.sendall(raster_data)
            sock.close()

            logger.info(
                f"{copies} label copies printed successfully "
                f"(tape: {label_size}, threshold: {threshold}, rotate: {rotate})"
            )
            return True

        except Exception as e:
            import traceback
            logger.error(f"Error printing label: {e}\n{traceback.format_exc()}")
            raise

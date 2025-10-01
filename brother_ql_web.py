#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This is a web service to print labels on Brother QL label printers.
"""

import sys, logging, random, json, argparse
from typing import Dict, Any
import base64
from io import BytesIO

from bottle import run, route, get, post, response, request, static_file
from brother_ql.devicedependent import models
from brother_ql.backends import backend_factory, guess_backend
from jinja2 import Environment, FileSystemLoader
import os
from PIL import Image, ImageDraw

from printer_service import LabelPrinterService
from printer_manager import PrinterManager

logger = logging.getLogger(__name__)

printer_manager = None

# Setup Jinja2 template environment
template_dir = os.path.join(os.path.dirname(__file__), "views")
jinja_env = Environment(loader=FileSystemLoader(template_dir))


def generate_test_image(width=300, height=150):
    """Generate a simple test image with geometric shapes"""
    # Create a white background
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    # Draw some simple geometric shapes for testing
    # Black border
    draw.rectangle([0, 0, width - 1, height - 1], outline="black", width=2)

    # Diagonal lines
    draw.line([0, 0, width, height], fill="black", width=2)
    draw.line([width, 0, 0, height], fill="black", width=2)

    # Centered rectangle
    rect_width = width // 3
    rect_height = height // 3
    rect_x = (width - rect_width) // 2
    rect_y = (height - rect_height) // 2
    draw.rectangle(
        [rect_x, rect_y, rect_x + rect_width, rect_y + rect_height],
        outline="black",
        fill="lightgray",
        width=2,
    )

    # Four corner circles
    circle_radius = min(width, height) // 10
    positions = [
        (circle_radius, circle_radius),  # top-left
        (width - circle_radius, circle_radius),  # top-right
        (circle_radius, height - circle_radius),  # bottom-left
        (width - circle_radius, height - circle_radius),  # bottom-right
    ]

    for x, y in positions:
        draw.ellipse(
            [
                x - circle_radius,
                y - circle_radius,
                x + circle_radius,
                y + circle_radius,
            ],
            outline="black",
            fill="black",
        )

    return image


def image_to_base64(image):
    """Convert PIL Image to base64 string"""
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@route("/")
def index():
    """Serve the printer management interface"""
    try:
        # Get available printers
        printers = printer_manager.list_printers() if printer_manager else []

        template = jinja_env.get_template("printer_management.jinja2")
        return template.render(
            website={
                "HTML_TITLE": "Printer Manager",
                "PAGE_TITLE": "Brother QL Printer Manager",
                "PAGE_HEADLINE": "Manage your printers",
            },
            printers=printers,
        )
    except Exception as e:
        logger.error(f"Error rendering printer management: {e}")
        return f"<h1>Error</h1><p>Failed to load printer management: {str(e)}</p>"


@route("/static/<filename:path>")
def serve_static(filename):
    return static_file(filename, root="./static")


@route("/api")
def api_documentation():
    """Serve API documentation"""
    return static_file("API_DOCS.md", root=".")


@post("/api/print")
def print_label():
    """Print a label directly via HTTP request"""
    try:
        data = request.json
        if not data or ("image" not in data and "images" not in data):
            response.status = 400
            return {"error": "Image data is required"}

        # Extract parameters with defaults from config
        threshold = data.get("threshold", 70)
        rotate = data.get("rotate", "auto")
        copies = data.get("copies", 1)
        printer_name = data.get("printer", None)

        # Validate copies parameter
        try:
            copies = int(copies)
            if copies < 1:
                response.status = 400
                return {"error": "Number of copies must be at least 1"}
            if copies > 100:
                response.status = 400
                return {"error": "Number of copies cannot exceed 100"}
        except (ValueError, TypeError):
            response.status = 400
            return {"error": "Invalid copies parameter, must be a positive integer"}

        # Get the printer service and determine label size
        if printer_name:
            printer_service = printer_manager.get_printer_service(printer_name)
            if not printer_service:
                response.status = 400
                return {"error": f"Printer '{printer_name}' not found"}

            # Get printer ID to find default label size
            printer_id = None
            for printer in printer_manager.list_printers():
                if printer["display_name"] == printer_name:
                    printer_id = printer["printer_id"]
                    break

            # Use specified label size or printer's default
            label_size = data.get(
                "label_size",
                (
                    printer_manager.get_default_label_size(printer_id)
                    if printer_id
                    else "62"
                ),
            )
        else:
            # Use default printer
            default_printer = printer_manager.get_default_printer()
            if not default_printer:
                response.status = 400
                return {"error": "No printers available"}
            printer_service = printer_manager.get_printer_service(default_printer)

            # Get default printer's default label size
            printer_id = None
            for printer in printer_manager.list_printers():
                if printer["display_name"] == default_printer:
                    printer_id = printer["printer_id"]
                    break

            label_size = data.get(
                "label_size",
                (
                    printer_manager.get_default_label_size(printer_id)
                    if printer_id
                    else "62"
                ),
            )

        # Print the label directly
        images = data.get("images", [data.get("image", [])])
        for image in images:
            printer_service.print_label(
                image_data=image,
                label_size=label_size,
                threshold=threshold,
                rotate=rotate,
                copies=copies,
            )

        copies_text = f"{copies} copies" if copies > 1 else "1 copy"
        labels_text = f"{len(images)} labels" if len(images) > 1 else "1 label"
        return {"success": True, "message": f"{labels_text} printed successfully ({copies_text})"}
    except Exception as e:
        import traceback
        logger.error("Error printing label", exc_info=True)
        response.status = 500
        tb_str = traceback.format_exc()
        return {"error": str(e), "traceback": tb_str}


@get("/api/printers")
def list_printers():
    """List all available printers"""
    try:
        printers = printer_manager.list_printers()
        return {"printers": printers}
    except Exception as e:
        logger.error(f"Error listing printers: {e}")
        response.status = 500
        return {"error": str(e)}


@post("/api/printers")
def add_printer():
    """Add a manual printer"""
    try:
        data = request.json

        if not data or "printer_id" not in data or "address" not in data:
            response.status = 400
            return {"error": "printer_id and address are required"}

        printer_id = data["printer_id"]
        address = data["address"]
        port = data.get("port", 9100)
        model = data.get("model", "QL-500")
        display_name = data.get("display_name")
        default_label_size = data.get("default_label_size", "62")

        success = printer_manager.add_manual_printer(
            printer_id, address, port, model, display_name, default_label_size
        )

        if success:
            return {"success": True, "message": "Printer added successfully"}
        else:
            response.status = 400
            return {"error": "Failed to add printer"}

    except Exception as e:
        logger.error(f"Error adding printer: {e}")
        response.status = 500
        return {"error": str(e)}


@post("/api/printers/<printer_id>/display-name")
def set_printer_display_name(printer_id):
    """Set display name for a printer"""
    try:
        data = request.json

        if not data or "display_name" not in data:
            response.status = 400
            return {"error": "display_name is required"}

        display_name = data["display_name"]

        success = printer_manager.set_display_name(printer_id, display_name)

        if success:
            return {"success": True, "message": "Display name updated successfully"}
        else:
            response.status = 400
            return {"error": "Failed to update display name or printer not found"}

    except Exception as e:
        logger.error(f"Error setting display name: {e}")
        response.status = 500
        return {"error": str(e)}


@post("/api/printers/<printer_id>/remove")
def remove_printer(printer_id):
    """Remove a manually added printer"""
    try:
        success = printer_manager.remove_printer(printer_id)

        if success:
            return {"success": True, "message": "Printer removed successfully"}
        else:
            response.status = 400
            return {"error": "Failed to remove printer or printer not found"}

    except Exception as e:
        logger.error(f"Error removing printer: {e}")
        response.status = 500
        return {"error": str(e)}


@post("/api/printers/<printer_id>/test-print")
def test_print_printer(printer_id):
    """Print a test label on a specific printer"""
    try:
        # Get the printer display name
        display_name = None
        default_label_size = "62"  # fallback
        printers = printer_manager.list_printers()
        for printer in printers:
            if printer["printer_id"] == printer_id:
                display_name = printer["display_name"]
                default_label_size = printer.get("default_label_size", "62")
                break

        if not display_name:
            response.status = 404
            return {"error": f"Printer with ID '{printer_id}' not found"}

        # Get the printer service
        printer_service = printer_manager.get_printer_service(display_name)
        if not printer_service:
            response.status = 400
            return {"error": f"Could not connect to printer '{display_name}'"}

        # Generate test image
        test_image = generate_test_image()
        image_base64 = image_to_base64(test_image)

        # Print the test label using the printer's default label size
        result = printer_service.print_label(
            image_data=image_base64,
            label_size=default_label_size,
            threshold=70,
            rotate="auto",
            copies=1,  # Test prints are always single copy
        )

        return {
            "success": True,
            "message": f"Test label printed successfully on '{display_name}' (size: {default_label_size})",
        }
    except Exception as e:
        logger.error(f"Error printing test label: {e}")
        response.status = 500
        return {"error": str(e)}


@post("/api/printers/<printer_id>/default-label-size")
def set_printer_default_label_size(printer_id):
    """Set default label size for a printer"""
    try:
        data = request.json

        if not data or "default_label_size" not in data:
            response.status = 400
            return {"error": "default_label_size is required"}

        label_size = data["default_label_size"]

        # Validate label size (basic validation)
        valid_sizes = [
            "12",
            "29",
            "38",
            "50",
            "54",
            "62",
            "62red",
            "102",
            "17x54",
            "17x87",
            "23x23",
            "29x42",
            "29x90",
            "38x90",
            "39x48",
            "52x29",
            "62x29",
            "62x100",
        ]
        if label_size not in valid_sizes:
            response.status = 400
            return {
                "error": f"Invalid label size. Valid sizes: {', '.join(valid_sizes)}"
            }

        success = printer_manager.set_default_label_size(printer_id, label_size)

        if success:
            return {
                "success": True,
                "message": "Default label size updated successfully",
            }
        else:
            response.status = 400
            return {"error": "Failed to update default label size or printer not found"}

    except Exception as e:
        logger.error(f"Error setting default label size: {e}")
        response.status = 500
        return {"error": str(e)}


def main():
    global DEBUG, BACKEND_CLASS, printer_manager
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=False)
    parser.add_argument(
        "--loglevel", type=lambda x: getattr(logging, x.upper()), default=False
    )

    parser.add_argument(
        "--model",
        default=False,
        choices=models,
        help="The model of your printer (default: QL-500)",
    )
    parser.add_argument(
        "--disable-printer-service",
        action="store_true",
        help="Disable the printer service",
    )
    parser.add_argument(
        "printer",
        nargs="?",
        default=False,
        help="String descriptor for the printer to use (like tcp://192.168.0.23:9100 or file:///dev/usb/lp0)",
    )
    args = parser.parse_args()

    if args.port:
        PORT = args.port
    else:
        PORT = 8013

    if args.loglevel:
        LOGLEVEL = args.loglevel
    else:
        LOGLEVEL = "WARNING"

    if LOGLEVEL == "DEBUG":
        DEBUG = True
    else:
        DEBUG = False

    logging.basicConfig(level=LOGLEVEL)

    BACKEND_CLASS = backend_factory("network")["backend_class"]

    if not args.disable_printer_service:
        # Initialize printer manager
        printer_manager = PrinterManager(BACKEND_CLASS)
        # Start discovery after initialization
        printer_manager.start_discovery()

    try:
        # Start web server
        run(host="0.0.0.0", port=PORT, debug=DEBUG)
    finally:
        # Clean shutdown
        if printer_manager:
            printer_manager.shutdown()


if __name__ == "__main__":
    main()

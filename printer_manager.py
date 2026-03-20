import logging
import json
import os
import threading
from typing import Dict, List, Optional, Any
from printer_discovery import PrinterDiscoveryService, PrinterInfo
from printer_service import LabelPrinterService
from ptouch_printer_service import PTouchPrinterService

logger = logging.getLogger(__name__)


class PrinterManager:
    def __init__(self, backend_class: Any):
        self.backend_class = backend_class
        self.printer_configs_file = "printer_configs.json"
        self.printer_display_names: Dict[str, str] = {}  # printer_id -> display_name
        self.printer_default_label_sizes: Dict[str, str] = (
            {}
        )  # printer_id -> label_size
        self.printer_services: Dict[str, LabelPrinterService] = (
            {}
        )  # display_name -> service
        self.discovery_service = PrinterDiscoveryService(
            on_printer_found=self._on_printer_found,
            on_printer_removed=self._on_printer_removed,
        )
        self._lock = threading.Lock()

        # Load saved configurations
        self._load_printer_configs()

    def start_discovery(self):
        """Start the printer discovery service"""
        self.discovery_service.start_discovery()

    def _load_printer_configs(self):
        """Load printer configurations from file"""
        try:
            if os.path.exists(self.printer_configs_file):
                with open(self.printer_configs_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.printer_display_names = data.get("display_names", {})
                    self.printer_default_label_sizes = data.get(
                        "default_label_sizes", {}
                    )

                    # Load manual printers
                    manual_printers = data.get("manual_printers", {})
                    for printer_id, printer_info in manual_printers.items():
                        self.discovery_service.add_manual_printer(
                            printer_id,
                            printer_info["address"],
                            printer_info.get("port", 9100),
                            printer_info.get("model", "QL-500"),
                        )

                logger.info(
                    f"Loaded {len(self.printer_display_names)} printer configurations"
                )
        except Exception as e:
            logger.error(f"Failed to load printer configurations: {e}")

    def _save_printer_configs(self):
        """Save printer configurations to file"""
        try:
            # Get manual printers
            manual_printers = {}
            for (
                printer_id,
                printer_info,
            ) in self.discovery_service.get_printers().items():
                if printer_info.status == "Manual":  # Mark manual printers
                    manual_printers[printer_id] = {
                        "address": printer_info.address,
                        "port": printer_info.port,
                        "model": printer_info.model,
                    }

            data = {
                "display_names": self.printer_display_names,
                "default_label_sizes": self.printer_default_label_sizes,
                "manual_printers": manual_printers,
            }
            logger.info(f"Saving printer configs: {data}")

            with open(self.printer_configs_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.info("Printer configurations saved")
        except Exception as e:
            logger.error(f"Failed to save printer configurations: {e}")

    def _on_printer_found(self, printer_info: PrinterInfo):
        """Called when a new printer is discovered"""
        try:
            with self._lock:
                printer_id = printer_info.name
                logger.info(f"Printer found: {printer_id}")

                # Set default display name if not already set
                if printer_id not in self.printer_display_names:
                    self.printer_display_names[printer_id] = printer_info.name

                # Set default label size if not already set
                if printer_id not in self.printer_default_label_sizes:
                    if printer_info.model.upper().startswith("PT-"):
                        self.printer_default_label_sizes[printer_id] = "36mm"
                    else:
                        self.printer_default_label_sizes[printer_id] = "62"

                    self._save_printer_configs()
        except Exception as e:
            logger.error(f"Error in _on_printer_found: {e}")

    def _on_printer_removed(self, printer_info: PrinterInfo):
        """Called when a printer is removed"""
        try:
            with self._lock:
                printer_id = printer_info.name
                display_name = self.printer_display_names.get(printer_id)
                logger.info(f"Printer removed: {printer_id} {display_name}")

                # Remove printer service if it exists
                if display_name and display_name in self.printer_services:
                    del self.printer_services[display_name]
        except Exception as e:
            logger.error(f"Error in _on_printer_removed: {e}")

    def get_printer_service(self, display_name: str) -> Optional[LabelPrinterService]:
        """Get or create a printer service for the given display name"""
        with self._lock:
            if display_name in self.printer_services:
                return self.printer_services[display_name]

            # Find printer by display name
            printer_id = None
            for pid, dname in self.printer_display_names.items():
                if dname == display_name:
                    printer_id = pid
                    break

            if not printer_id:
                return None

            printer_info = self.discovery_service.get_printer(printer_id)
            if not printer_info:
                return None

            # Create and cache the service based on printer type
            printer_address = f"tcp://{printer_info.address}:{printer_info.port}"
            if printer_info.model.upper().startswith("PT-"):
                service = PTouchPrinterService(
                    printer_info.model,
                    printer_address,
                )
            else:
                service = LabelPrinterService(
                    printer_info.model,
                    printer_address,
                    self.backend_class,
                )
            logger.info(f"Creating service for {display_name}")
            self.printer_services[display_name] = service

            return service

    def get_default_label_size(self, printer_id: str) -> str:
        """Get the default label size for a printer"""
        with self._lock:
            return self.printer_default_label_sizes.get(printer_id, "62")

    def set_default_label_size(self, printer_id: str, label_size: str) -> bool:
        """Set the default label size for a printer"""
        with self._lock:
            if printer_id not in self.discovery_service.get_printers():
                return False

            self.printer_default_label_sizes[printer_id] = label_size
            self._save_printer_configs()
            return True

    def list_printers(self, include_offline: bool = False) -> List[Dict[str, Any]]:
        """
        List all available printers with their display names and status
        
        Args:
            include_offline: If True, include offline printers in the list. Default is False.
        
        Returns:
            List of printer dictionaries with connectivity status
        """
        # Get printers from discovery service (this has its own lock)
        discovered_printers = self.discovery_service.get_printers()
        logger.info(f"Discovered printers: {discovered_printers}")

        # Only lock for the display names access
        with self._lock:
            display_names_copy = self.printer_display_names.copy()
            label_sizes_copy = self.printer_default_label_sizes.copy()

        printers = []
        for printer_id, printer_info in discovered_printers.items():
            display_name = display_names_copy.get(printer_id, printer_id)
            default_label_size = label_sizes_copy.get(printer_id, "62")

            # Check if printer is online
            printer_address = f"tcp://{printer_info.address}:{printer_info.port}"
            if printer_info.model.upper().startswith("PT-"):
                service = PTouchPrinterService(
                    printer_info.model,
                    printer_address,
                )
            else:
                service = LabelPrinterService(
                    printer_info.model,
                    printer_address,
                    self.backend_class,
                )
            is_online = service.is_online(timeout=0.5)
            
            # Skip offline printers unless explicitly requested
            if not is_online and not include_offline:
                logger.debug(f"Skipping offline printer: {printer_id} ({display_name})")
                continue

            printer_data = printer_info.to_dict()
            printer_data["display_name"] = display_name
            printer_data["printer_id"] = printer_id
            printer_data["default_label_size"] = default_label_size
            printer_data["is_online"] = is_online

            printers.append(printer_data)

        return printers

    def set_display_name(self, printer_id: str, display_name: str) -> bool:
        """Set display name for a printer"""
        with self._lock:
            if printer_id not in self.discovery_service.get_printers():
                return False

            # Check if display name is already used
            for pid, dname in self.printer_display_names.items():
                if dname == display_name and pid != printer_id:
                    return False  # Display name already in use

            old_display_name = self.printer_display_names.get(printer_id)
            self.printer_display_names[printer_id] = display_name

            # Update printer service cache
            if old_display_name and old_display_name in self.printer_services:
                service = self.printer_services.pop(old_display_name)
                self.printer_services[display_name] = service

            self._save_printer_configs()
            return True

    def add_manual_printer(
        self,
        printer_id: str,
        address: str,
        port: int = 9100,
        model: str = "QL-500",
        display_name: Optional[str] = None,
        default_label_size: str = "62",
    ) -> bool:
        """Manually add a printer"""
        try:
            self.discovery_service.add_manual_printer(printer_id, address, port, model)

            # Mark as manual
            if printer_id in self.discovery_service.printers:
                self.discovery_service.printers[printer_id].status = "Manual"

            if display_name:
                self.printer_display_names[printer_id] = display_name
            elif printer_id not in self.printer_display_names:
                self.printer_display_names[printer_id] = printer_id

            # Set default label size
            self.printer_default_label_sizes[printer_id] = default_label_size

            self._save_printer_configs()
            return True
        except Exception as e:
            logger.error(f"Failed to add manual printer: {e}")
            return False

    def remove_printer(self, printer_id: str) -> bool:
        """Remove a manually added printer"""
        with self._lock:
            if printer_id not in self.discovery_service.get_printers():
                return False

            printer_info = self.discovery_service.get_printer(printer_id)
            if printer_info and printer_info.status != "Manual":
                return False  # Can only remove manual printers

            # Remove from discovery service
            if printer_id in self.discovery_service.printers:
                del self.discovery_service.printers[printer_id]

            # Remove display name and default label size
            display_name = self.printer_display_names.pop(printer_id, None)
            self.printer_default_label_sizes.pop(printer_id, None)

            # Remove service
            if display_name and display_name in self.printer_services:
                del self.printer_services[display_name]

            self._save_printer_configs()
            return True

    def get_default_printer(self) -> Optional[str]:
        """Get the default printer display name"""
        printers = self.list_printers()
        if not printers:
            return None

        # Return the first printer, or the one marked as default
        for printer in printers:
            if printer["display_name"] == "Default Printer":
                return printer["display_name"]

        return printers[0]["display_name"]

    def shutdown(self):
        """Shutdown the printer manager"""
        self.discovery_service.stop_discovery()
        self._save_printer_configs()

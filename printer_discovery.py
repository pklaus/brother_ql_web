import logging
import threading
import time
from typing import Dict, List, Optional, Callable
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
import socket

logger = logging.getLogger(__name__)


class PrinterInfo:
    def __init__(self, name: str, address: str, port: int, model: str = "Unknown"):
        self.name = name
        self.address = address
        self.port = port
        self.model = model
        self.last_seen = time.time()
        self.status = "Unknown"

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "address": self.address,
            "port": self.port,
            "model": self.model,
            "last_seen": self.last_seen,
            "status": self.status,
            "connection_string": f"tcp://{self.address}:{self.port}",
        }


class PrinterDiscoveryService(ServiceListener):
    def __init__(
        self,
        on_printer_found: Optional[Callable] = None,
        on_printer_removed: Optional[Callable] = None,
    ):
        self.printers: Dict[str, PrinterInfo] = {}
        self.zeroconf = None
        self.browser = None
        self.on_printer_found = on_printer_found
        self.on_printer_removed = on_printer_removed
        self._lock = threading.Lock()

    def start_discovery(self):
        """Start the printer discovery service"""
        print("Starting printer discovery service")
        try:
            self.zeroconf = Zeroconf()
            # Brother printers typically advertise on these service types
            service_types = [
                "_ipp._tcp.local.",
                "_printer._tcp.local.",
                "_pdl-datastream._tcp.local.",
            ]

            self.browsers = []
            for service_type in service_types:
                browser = ServiceBrowser(self.zeroconf, service_type, self)
                self.browsers.append(browser)

            logger.info("Printer discovery service started")
        except Exception as e:
            logger.error(f"Failed to start printer discovery: {e}")

    def stop_discovery(self):
        """Stop the printer discovery service"""
        try:
            if self.zeroconf:
                self.zeroconf.close()
            logger.info("Printer discovery service stopped")
        except Exception as e:
            logger.error(f"Failed to stop printer discovery: {e}")

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a new service is discovered"""
        print(f"Discovered service: {name}")
        try:
            info = zc.get_service_info(type_, name)
            if info and self._is_brother_printer(info):
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port

                # Extract model from service name or properties
                model = self._extract_model(info)
                if model.lower().startswith("ql-") or model.lower().startswith("pt-"):
                    printer_name = (
                        info.server.replace(".local.", "") if info.server else name
                    )

                    # Brother printers advertise on various ports (515 LPD, 631 IPP)
                    # but we use port 9100 (raw TCP) for the raster protocol
                    port = 9100

                    printer_info = PrinterInfo(printer_name, address, port, model)
                    with self._lock:
                        self.printers[printer_name] = printer_info

                    logger.info(
                        f"Discovered Brother printer: {printer_name} at {address}:{port}"
                    )

                    if self.on_printer_found:
                        self.on_printer_found(printer_info)

        except Exception as e:
            logger.error(f"Error adding service {name}: {e}")

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is removed"""
        try:
            # Find printer by service name
            printer_to_remove = None
            for printer_name, printer_info in self.printers.items():
                if name.startswith(printer_name) or printer_name in name:
                    printer_to_remove = printer_name
                    break

            if printer_to_remove:
                with self._lock:
                    removed_printer = self.printers.pop(printer_to_remove)
                logger.info(f"Removed printer: {printer_to_remove}")

                if self.on_printer_removed:
                    self.on_printer_removed(removed_printer)

        except Exception as e:
            logger.error(f"Error removing service {name}: {e}")

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is updated"""
        # Treat updates as add operations
        self.add_service(zc, type_, name)

    def _is_brother_printer(self, info) -> bool:
        """Check if the discovered service is a Brother printer"""
        try:
            # Check if it's a Brother printer based on various criteria
            name_lower = info.name.lower()
            server_lower = info.server.lower() if info.server else ""

            brother_indicators = ["brother", "ql-", "bql", "pt-"]
            return any(
                indicator in name_lower or indicator in server_lower
                for indicator in brother_indicators
            )
        except:
            return False

    def _extract_model(self, info) -> str:
        """Extract printer model from service info"""
        try:
            name = info.name.lower()

            # Common Brother QL models
            models = [
                "ql-500",
                "ql-550",
                "ql-560",
                "ql-570",
                "ql-580n",
                "ql-600",
                "ql-650td",
                "ql-700",
                "ql-710w",
                "ql-720nw",
                "ql-800",
                "ql-810w",
                "ql-820nwb",
                "ql-1100",
                "ql-1110nwb",
                "pt-p900w",
                "pt-p950nw",
            ]

            for model in models:
                if model in name:
                    return model.upper()

            # Check properties for model info
            if info.properties:
                for key, value in info.properties.items():
                    if b"model" in key.lower() or b"ty" in key.lower():
                        return value.decode("utf-8", errors="ignore")

            # Check if service name contains PT indicators
            pt_indicators = ["pt-", "p-touch"]
            if any(indicator in name for indicator in pt_indicators):
                return "Brother PT"

            return "Brother QL"
        except:
            return "Unknown"

    def get_printers(self) -> Dict[str, PrinterInfo]:
        """Get all discovered printers"""
        with self._lock:
            return self.printers.copy()

    def get_printer(self, name: str) -> Optional[PrinterInfo]:
        """Get a specific printer by name"""
        with self._lock:
            return self.printers.get(name)

    def add_manual_printer(
        self, name: str, address: str, port: int = 9100, model: str = "QL-500"
    ):
        """Manually add a printer"""
        with self._lock:
            printer_info = PrinterInfo(name, address, port, model)
            self.printers[name] = printer_info
            logger.info(f"Manually added printer: {name} at {address}:{port}")

            if self.on_printer_found:
                self.on_printer_found(printer_info)

"""
OPC UA Client Module
Handles connection and communication with Beckhoff TwinCAT PLC
Supports username/password authentication and certificates
"""

from opcua import Client, ua
from opcua.crypto import security_policies
import logging
import os
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class OPCUAClient:
    """OPC UA Client for PLC communication with security support"""
    
    def __init__(self, server_url: str, namespace: int = 4,
                 username: str = None, password: str = None,
                 security_policy: str = "None", security_mode: str = "None",
                 certificate_path: str = None, private_key_path: str = None):
        """
        Initialize OPC UA client

        Args:
            server_url:       OPC UA server URL (e.g., "opc.tcp://192.168.0.0:4840")
            namespace:        Namespace index (default: 4 for TwinCAT)
            username:         Username for authentication
            password:         Password for authentication
            security_policy:  "None", "Basic256", "Basic256Sha256"
            security_mode:    "None", "Sign", "SignAndEncrypt"
            certificate_path: Path to client certificate (.der file)
            private_key_path: Path to client private key (.pem file)
        """
        self.server_url       = server_url
        self.namespace        = namespace
        self.username         = username
        self.password         = password
        self.security_policy  = security_policy
        self.security_mode    = security_mode
        self.certificate_path = certificate_path
        self.private_key_path = private_key_path

        self.client    = None
        self.connected = False
        self.nodes     = {}  # Cache for node objects

    def _ensure_certificates(self):
        """Check if certificates exist"""
        if not self.certificate_path or not self.private_key_path:
            return False

        if os.path.exists(self.certificate_path) and os.path.exists(self.private_key_path):
            logger.info("Using existing certificates")
            return True
        else:
            logger.error("Certificates not found! Run generate_certificates.py first")
            return False

    def connect(self) -> bool:
        """
        Establish connection to OPC UA server with security

        Returns:
            bool: True if connected successfully
        """
        try:
            logger.info(f"Connecting to OPC UA server: {self.server_url}")
            logger.info(f"Security: {self.security_policy} / {self.security_mode}")
            if self.username:
                logger.info(f"Username: {self.username}")

            self.client = Client(self.server_url)

            # Set up security if needed
            if self.security_policy != "None" and self.security_mode != "None":
                if self.certificate_path and self.private_key_path:
                    self._ensure_certificates()

                    if os.path.exists(self.certificate_path) and os.path.exists(self.private_key_path):
                        if self.security_policy == "Basic256Sha256":
                            policy = security_policies.SecurityPolicyBasic256Sha256
                        elif self.security_policy == "Basic256":
                            policy = security_policies.SecurityPolicyBasic256
                        else:
                            policy = security_policies.SecurityPolicyBasic128Rsa15

                        self.client.set_security(
                            policy,
                            certificate_path=self.certificate_path,
                            private_key_path=self.private_key_path
                        )
                        logger.info("[OK] Security configured with certificates")
                    else:
                        logger.error("Certificates not found!")
                        return False

            # Set username/password
            if self.username and self.password:
                self.client.set_user(self.username)
                self.client.set_password(self.password)

            self.client.connect()
            self.connected = True
            logger.info("[OK] Connected to OPC UA server")

            return True

        except Exception as e:
            logger.error(f"[ERROR] Failed to connect to OPC UA server")
            logger.error(f"   Error: {e}")
            logger.error(f"   Server: {self.server_url}")
            if self.username:
                logger.error(f"   Username: {self.username}")
            logger.error(f"   Security: {self.security_policy} / {self.security_mode}")

            if "BadUserAccessDenied" in str(e):
                logger.error("   -> Check username/password!")
            elif "BadCertificate" in str(e):
                logger.error("   -> Certificate not trusted by server!")
                logger.error("   -> Import certificate in TwinCAT TF6100 trusted certificates")
            elif "Connection refused" in str(e):
                logger.error("   -> Check if TwinCAT OPC UA server is running")
                logger.error("   -> Check firewall (port 4840)")

            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from OPC UA server"""
        if self.client and self.connected:
            try:
                self.client.disconnect()
                self.connected = False
                logger.info("Disconnected from OPC UA server")
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")

    def get_node(self, node_id: str):
        """
        Get node object from node ID (with caching for performance)

        Args:
            node_id: Node identifier (e.g., "ns=4;s=MAIN.Dyno_Speed_RPM")

        Returns:
            Node object or None
        """
        if node_id not in self.nodes:
            try:
                self.nodes[node_id] = self.client.get_node(node_id)
            except Exception as e:
                logger.error(f"Failed to get node {node_id}: {e}")
                return None
        return self.nodes[node_id]

    def read_variable(self, node_id: str) -> Any:
        """
        Read single variable from PLC

        Args:
            node_id: Node identifier

        Returns:
            Variable value or None
        """
        if not self.connected:
            logger.warning("Not connected to OPC UA server")
            return None

        try:
            node = self.get_node(node_id)
            if node:
                return node.get_value()
        except Exception as e:
            logger.error(f"Error reading {node_id}: {e}")

        return None

    def write_variable(self, node_id: str, value: Any) -> bool:
        """
        Write value to PLC variable

        Args:
            node_id: Node identifier
            value:   Value to write

        Returns:
            bool: True if successful
        """
        if not self.connected:
            logger.warning("Not connected to OPC UA server")
            return False

        try:
            print(f"[DEBUG] Getting node: {node_id}")
            node = self.get_node(node_id)

            if node:
                print(f"[DEBUG] Node found, writing value: {value}")
                data_type = node.get_data_type_as_variant_type()
                print(f"[DEBUG] Data type: {data_type}")

                dv = ua.DataValue(ua.Variant(value, data_type))
                node.set_value(dv)

                print(f"[DEBUG] Write completed successfully")
                return True
            else:
                logger.error(f"Could not get node: {node_id}")
                return False

        except Exception as e:
            logger.error(f"Error writing to {node_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def read_multiple(self, variables: List[Dict]) -> Dict[str, Any]:
        """
        Read multiple variables in a SINGLE batch request (low latency)
        Falls back to sequential reading if batch fails.

        Args:
            variables: List of dicts with 'name' and 'node_id'

        Returns:
            Dict mapping variable names to values
        """
        if not self.connected:
            logger.warning("Not connected to OPC UA server")
            return {var['name']: None for var in variables}

        # ═══════════════════════════════════════════════════════════
        # BATCH READ - Single OPC UA request for all variables
        # This reduces latency from N×12ms to ~12ms total
        # ═══════════════════════════════════════════════════════════
        try:
            # Build list of nodes (use cache)
            nodes = []
            names = []
            for var_info in variables:
                node = self.get_node(var_info['node_id'])
                if node:
                    nodes.append(node)
                    names.append(var_info['name'])
                else:
                    logger.warning(f"Skipping node: {var_info['node_id']}")

            if not nodes:
                return {var['name']: None for var in variables}

            # Single batch read request
            values = self.client.get_values(nodes)

            # Map names to values
            results = {}
            for name, value in zip(names, values):
                results[name] = value

            # Add None for any skipped nodes
            for var_info in variables:
                if var_info['name'] not in results:
                    results[var_info['name']] = None

            logger.debug(f"Batch read: {len(nodes)} variables in single request")
            return results

        except Exception as e:
            # ═══════════════════════════════════════════════════════
            # FALLBACK - Sequential reading if batch fails
            # ═══════════════════════════════════════════════════════
            logger.warning(f"Batch read failed ({e}), falling back to sequential")
            results = {}
            for var_info in variables:
                name    = var_info['name']
                node_id = var_info['node_id']
                results[name] = self.read_variable(node_id)
            return results

    def write_multiple(self, variables: Dict[str, Any]) -> bool:
        """
        Write multiple variables

        Args:
            variables: Dict mapping node_ids to values

        Returns:
            bool: True if all writes successful
        """
        success = True
        for node_id, value in variables.items():
            if not self.write_variable(node_id, value):
                success = False
        return success

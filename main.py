"""
PLC Gateway Tool - Main Application
Bidirectional OPC UA <-> MQTT Gateway with Multi-Format Data Logging

Author: Master Thesis - TH Deggendorf
Description: Tool for automated PLC data import/export with security support
"""

import yaml
import logging
import time
import signal
import sys
from influxdb_handler import InfluxDBHandler
from opcua_client import OPCUAClient
from mqtt_handler import MQTTHandler
from data_logger import DataLogger

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

def setup_logging(config: dict):
    """Configure application logging"""
    log_level = getattr(logging, config.get('level', 'INFO'))
    log_file = config.get('file', 'gateway.log')
    console_enabled = config.get('console', True)
    
    handlers = [logging.FileHandler(log_file)]
    if console_enabled:
        handlers.append(logging.StreamHandler(sys.stdout))
    
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] %(levelname)-8s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers
    )

logger = logging.getLogger(__name__)

# ============================================================================
# MAIN GATEWAY CLASS
# ============================================================================

class PLCGateway:
    """Main gateway application class"""
    
    def __init__(self, config_path='config.yaml'):
        # Load configuration
        logger.info("=" * 70)
        logger.info("PLC GATEWAY TOOL - LOADING CONFIGURATION")
        logger.info("=" * 70)
        
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from: {config_path}")
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in configuration file: {e}")
            raise
        
        setup_logging(self.config.get('app_logging', {}))
        logger.info("Initializing components...")
        
        security_config = self.config['opcua'].get('security', {})
        self.opcua_client = OPCUAClient(
            self.config['opcua']['server_url'],
            self.config['opcua']['namespace'],
            username=security_config.get('username'),
            password=security_config.get('password'),
            security_policy=security_config.get('policy', 'None'),
            security_mode=security_config.get('mode', 'None'),
            certificate_path=security_config.get('certificate'),
            private_key_path=security_config.get('private_key')
        )
        logger.info("OPC UA client initialized")
        
        sparkplug_enabled = self.config.get('sparkplug', {}).get('enabled', False)

        if sparkplug_enabled:
            from sparkplug_handler import SparkplugHandler
            self.sparkplug_handler = SparkplugHandler(self.config['sparkplug'])
            self.sparkplug_handler.configure_metrics(self.config['opcua']['read_variables'])
            self.mqtt_handler = None
            logger.info("[OK] Sparkplug B handler initialized")
        else:
            self.mqtt_handler = MQTTHandler(
                self.config['mqtt']['broker'],
                self.config['mqtt']['port'],
                self.config['mqtt']['client_id'],
                self.config['mqtt'].get('qos', 1)
            )
            self.sparkplug_handler = None
            logger.info("[OK] MQTT handler initialized")
        
        self.data_logger = DataLogger(self.config['logging'])
        logger.info("Data logger initialized")
        
        influxdb_config = self.config.get('influxdb', {})
        self.influxdb_handler = InfluxDBHandler(influxdb_config)
        logger.info("InfluxDB handler initialized")

        # Latency tracking
        self.latency_samples = []
        self.latency_max_ms  = 0.0
        self.latency_avg_ms  = 0.0
        
        self.running = False
        
        # Build topic-to-variable mapping
        self.topic_to_variable = {}
        for sub in self.config['mqtt']['subscribe_topics']:
            self.topic_to_variable[sub['topic']] = {
                'variable': sub['variable'],
                'type': sub.get('value_type', 'string')
            }
        
        logger.info("All components initialized successfully")
    
    def start(self) -> bool:
        logger.info("=" * 70)
        logger.info("STARTING PLC GATEWAY TOOL")
        logger.info("=" * 70)
        
        logger.info("Connecting to PLC via OPC UA...")
        if not self.opcua_client.connect():
            logger.error("Failed to connect to PLC. Check:")
            logger.error("  - PLC IP address in config.yaml")
            logger.error("  - TwinCAT is running and PLC is in RUN mode")
            logger.error("  - Username/password are correct")
            logger.error("  - Firewall allows port 4840")
            logger.error("  - Certificates are trusted in TwinCAT")
            return False

        if self.sparkplug_handler:
            logger.info("Connecting to MQTT broker with Sparkplug B...")
            if not self.sparkplug_handler.connect():
                logger.error("[ERROR] Failed to connect with Sparkplug B")
                self.opcua_client.disconnect()
                return False
        else:
            logger.info("Connecting to MQTT broker (Plain MQTT)...")
            if not self.mqtt_handler.connect():
                logger.error("[ERROR] Failed to connect to MQTT broker")
                self.opcua_client.disconnect()
                return False
    
            # Wait for connection to stabilize
            time.sleep(2)
    
            logger.info("Subscribing to MQTT command topics...")
            self.mqtt_handler.subscribe(self.config['mqtt']['subscribe_topics'])
            self.mqtt_handler.set_command_callback(self.handle_mqtt_command)

            # ═══════════════════════════════════════════════════════════
            # INITIALIZE COMMAND TOPICS FOR IGNITION SCADA
            # Publish initial FALSE to all command topics so MQTT Engine
            # auto-creates the tags in Ignition tag browser.
            # Without this publish, Ignition never sees these topics
            # and command tags don't appear in the tag browser.
            # ═══════════════════════════════════════════════════════════
            logger.info("Initializing command topics for Ignition SCADA...")
            time.sleep(1)

            for sub in self.config['mqtt']['subscribe_topics']:
                topic = sub['topic']
                self.mqtt_handler.publish(topic, 'false')
                logger.info(f"  Initialized: {topic}")

            logger.info("[OK] Command topics initialized - tags now visible in Ignition")
            # ═══════════════════════════════════════════════════════════
        
        self.running = True
        
        logger.info("=" * 70)
        logger.info(" GATEWAY RUNNING SUCCESSFULLY")
        logger.info("=" * 70)
        logger.info("Press Ctrl+C to stop")
        logger.info("")
        
        return True
    
    def handle_mqtt_command(self, topic: str, payload: str):
        try:
            var_info = self.topic_to_variable.get(topic)
            if not var_info:
                logger.warning(f"Unknown topic: {topic}")
                return
            
            variable_name = var_info['variable']
            value_type    = var_info['type']
            
            node_id = None
            for var in self.config['opcua']['write_variables']:
                if var['name'] == variable_name:
                    node_id = var['node_id']
                    break
            
            if not node_id:
                logger.error(f"No node ID found for variable: {variable_name}")
                return
            
            if value_type == 'bool':
                value = payload.lower() in ['true', '1', 'on']
            elif value_type == 'float':
                value = float(payload)
            elif value_type == 'int':
                value = int(payload)
            else:
                value = payload

            # Send pulse for bool commands (TRUE then reset to FALSE)
            # PLC uses rising edge detection
            if value_type == 'bool' and value == True:
                success1 = self.opcua_client.write_variable(node_id, True)
                if success1:
                    logger.info(f"Command sent: {topic} = TRUE")
                    time.sleep(0.2)
                    success2 = self.opcua_client.write_variable(node_id, False)
                    if success2:
                        logger.info(f"Command reset: {topic} = FALSE")
                    else:
                        logger.warning(f"Failed to reset command: {topic}")
                else:
                    logger.error(f"Failed to send command: {topic}")
            else:
                success = self.opcua_client.write_variable(node_id, value)
                if success:
                    logger.info(f"Command executed: {topic} = {value}")
                else:
                    logger.error(f"Failed to execute command: {topic}")
            
        except ValueError as e:
            logger.error(f"Invalid value for {topic}: {payload} ({e})")
        except Exception as e:
            logger.error(f"Error handling command: {e}")
    
    def run(self):
        """Main execution loop"""
        interval   = self.config['logging']['interval']
        loop_count = 0
        
        try:
            while self.running:
                loop_count += 1

                # Measure OPC UA round trip latency
                t_start = time.perf_counter()
                data = self.opcua_client.read_multiple(
                    self.config['opcua']['read_variables']
                )
                t_end = time.perf_counter()

                latency_ms = (t_end - t_start) * 1000.0

                if latency_ms > self.latency_max_ms:
                    self.latency_max_ms = latency_ms

                self.latency_samples.append(latency_ms)
                if len(self.latency_samples) > 100:
                    self.latency_samples.pop(0)
                self.latency_avg_ms = sum(self.latency_samples) / len(self.latency_samples)

                # Publish sensor data to MQTT -> Ignition SCADA
                if self.sparkplug_handler:
                    self.sparkplug_handler.publish_data(data)
                else:
                    for name, value in data.items():
                        if value is not None:
                            topic = self.config['mqtt']['publish_topics'].get(name)
                            if topic:
                                self.mqtt_handler.publish(topic, value)
                                
                # Log data to local files
                if self.config['logging']['enabled']:
                    self.data_logger.log(data)
                
                # Extract values for InfluxDB
                speed            = data.get('speed', 0)
                torque           = data.get('torque', 0)
                power            = data.get('power', 0)
                motor_state      = data.get('motor_state', 0)
                system_ready     = data.get('system_ready', False)
                alarm_active     = data.get('alarm_active', False)
                runtime_hours    = data.get('runtime_hours', 0)
                temperature      = data.get('temperature', 0)
                efficiency       = data.get('efficiency', 0)
                electrical_power = data.get('electrical_power', 0)
                current          = data.get('current', 0)
                latency_avg      = self.latency_avg_ms
                latency_max      = self.latency_max_ms

                # Send to InfluxDB Cloud
                influxdb_config = self.config.get('influxdb', {})
                if influxdb_config.get('enabled', False):
                    self.influxdb_handler.write_data(
                        speed=speed,
                        torque=torque,
                        power=power,
                        motor_state=motor_state,
                        system_ready=system_ready,
                        alarm_active=alarm_active,
                        runtime_hours=runtime_hours,
                        temperature=temperature,
                        current=current,
                        efficiency=efficiency,
                        electrical_power=electrical_power,
                        latency_avg_ms=latency_avg,
                        latency_max_ms=latency_max
                    )
                
                # Print status every 10 loops
                if loop_count % 10 == 0:
                    state_names = {
                        0: "STOPPED",
                        1: "STARTING",
                        2: "RUNNING",
                        3: "STOPPING",
                        4: "FAULT"
                    }
                    state_name = state_names.get(motor_state, f"UNKNOWN({motor_state})")
                    
                    logger.info(
                        f"Status: Speed={speed:>7.1f} RPM | "
                        f"Torque={torque:>5.2f} Nm | "
                        f"Temp={temperature:>5.1f}C | "
                        f"Current={current:>5.3f}A | "
                        f"Eff={efficiency:>5.1f}% | "
                        f"Latency={latency_avg:>5.2f}ms | "
                        f"State={state_name}"
                    )
                
                time.sleep(interval)
        
        except KeyboardInterrupt:
            logger.info("")
            logger.info("Shutdown requested by user (Ctrl+C)")
        
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
        
        finally:
            self.stop()
    
    def stop(self):
        """Stop the gateway gracefully"""
        logger.info("=" * 70)
        logger.info("SHUTTING DOWN GATEWAY")
        logger.info("=" * 70)
        
        self.running = False
        
        logger.info("Disconnecting from MQTT...")
        if self.sparkplug_handler:
            self.sparkplug_handler.disconnect()
        elif self.mqtt_handler:
            self.mqtt_handler.disconnect()
        
        logger.info("Disconnecting from OPC UA...")
        self.opcua_client.disconnect()
        
        logger.info("Closing data logger...")
        self.data_logger.close()
        
        logger.info("Closing InfluxDB connection...")
        self.influxdb_handler.close()
        
        logger.info("=" * 70)
        logger.info("GATEWAY STOPPED SUCCESSFULLY")
        logger.info("=" * 70)

# ============================================================================
# SIGNAL HANDLER
# ============================================================================

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    logger.info("")
    logger.info("Interrupt signal received")
    sys.exit(0)

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    
    print("")
    print("=" * 70)
    print("  PLC GATEWAY TOOL - Master Thesis TH Deggendorf")
    print("  Bidirectional OPC UA <-> MQTT Gateway")
    print("=" * 70)
    print("")
    
    try:
        gateway = PLCGateway('config.yaml')
        if gateway.start():
            gateway.run()
    except FileNotFoundError:
        print("ERROR: config.yaml not found!")
        print("Please make sure config.yaml is in the same directory as main.py")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutdown requested")
        sys.exit(0)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

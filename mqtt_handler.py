"""
MQTT Handler Module
Publishes PLC data and subscribes to SCADA commands
Compatible with paho-mqtt 2.x
"""

import paho.mqtt.client as mqtt
import json
import logging
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)

class MQTTHandler:
    """MQTT Client for bidirectional communication"""
    
    def __init__(self, broker: str, port: int, client_id: str, qos: int = 1):
        self.broker = broker
        self.port = port
        self.client_id = client_id
        self.qos = qos
        self.client = None
        self.connected = False
        self.command_callback = None
        
    def connect(self) -> bool:
        try:
            logger.info(f"Connecting to MQTT broker: {self.broker}:{self.port}")
            
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=self.client_id
            )
            
            self.client.on_connect    = self._on_connect
            self.client.on_message    = self._on_message
            self.client.on_disconnect = self._on_disconnect
            
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False
    
    def disconnect(self):
        if self.client and self.connected:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("Disconnected from MQTT broker")
    
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.connected = True
            logger.info("[OK] Connected to MQTT broker")
        else:
            logger.error(f"Failed to connect to MQTT broker. Reason code: {reason_code}")
    
    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        if reason_code != 0:
            logger.warning(f"Unexpected disconnection. Reason code: {reason_code}")
    
    def _on_message(self, client, userdata, message):
        """Callback when message received from broker"""
        try:
            topic   = message.topic
            payload = message.payload.decode('utf-8')

            # ═══════════════════════════════════════════════════════
            # Log at INFO level so it always appears in gateway.log
            # Previously used DEBUG which was invisible in normal mode
            # ═══════════════════════════════════════════════════════
            logger.info(f"[MQTT CMD] Received: '{topic}' = '{payload}'")
            
            if self.command_callback:
                self.command_callback(topic, payload)
            else:
                logger.warning("[MQTT CMD] No command callback registered!")
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    def publish(self, topic: str, value: any, qos: int = None) -> bool:
        if not self.connected:
            logger.warning("Not connected to MQTT broker")
            return False
        
        if qos is None:
            qos = self.qos
        
        try:
            # Convert value to correct string format
            if isinstance(value, (dict, list)):
                payload = json.dumps(value)
            elif isinstance(value, bool):
                payload = 'true' if value else 'false'
            elif isinstance(value, float):
                payload = f"{value:.2f}"
            elif isinstance(value, int):
                payload = str(value)
            else:
                payload = str(value)
            
            result = self.client.publish(topic, payload, qos=qos)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published: {topic} -> {payload}")
                return True
            else:
                logger.error(f"Failed to publish to {topic}")
                return False
                
        except Exception as e:
            logger.error(f"Error publishing to {topic}: {e}")
            return False
    
    def subscribe(self, topics: List[Dict]):
        """Subscribe to command topics"""
        for topic_info in topics:
            topic = topic_info['topic']
            try:
                result = self.client.subscribe(topic, qos=self.qos)
                # Log at INFO so subscription confirmation always visible
                logger.info(f"[SUBSCRIBED] '{topic}' (result: {result})")
            except Exception as e:
                logger.error(f"Error subscribing to {topic}: {e}")
    
    def set_command_callback(self, callback: Callable):
        self.command_callback = callback
        logger.info("[OK] Command callback registered")
